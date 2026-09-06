"""最小驱动 —— 一个"参考 UI",不是框架的一部分。

它只做一件事:把 Event 流打到终端。整个文件两百行出头,
你要换成 Web / TUI / HTTP 服务,照抄 render() 换个出口即可 ——
框架层不知道 UI 的存在。
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import sys
import threading
import time
from pathlib import Path

from .core.agent import AgentSpec
from .core.env import describe, load_dotenv
from .core.events import Event
from .core.runtime import Runtime
from .workflow.starter import starter_flow

C = {
    "dim": "\033[2m", "red": "\033[31m", "grn": "\033[32m",
    "ylw": "\033[33m", "blu": "\033[34m", "mag": "\033[35m", "off": "\033[0m",
}


def render(ev: Event, *, verbose: bool = False) -> None:
    """Event → 终端。换 UI 就是换这一个函数。"""
    if ev.kind == "text":
        print(ev.text, flush=True)
    elif ev.kind == "prompt":
        if verbose:
            who = "→ subagent" if ev.payload.get("subagent") else "→"
            print(f"{C['dim']}{who} {ev.text[:300]}{C['off']}", flush=True)
    elif ev.kind == "thinking":
        if verbose:
            print(f"{C['dim']}{ev.text}{C['off']}", flush=True)
    elif ev.kind == "tool_call":
        # 摘要在 ev.text 里 —— normalize 已经从 file_path/command/pattern 里挑好了
        print(f"{C['blu']}⏺ {ev.tool}{C['off']} {C['dim']}{ev.text}{C['off']}", flush=True)
    elif ev.kind == "tool_result":
        if ev.payload.get("is_error"):
            print(f"  {C['red']}✗ {ev.text[:200]}{C['off']}", flush=True)
        elif verbose:
            print(f"  {C['dim']}{ev.text[:200]}{C['off']}", flush=True)
    elif ev.kind == "ask":
        # 要人回答。走的是同一条 Event 流 —— 换 UI 不用为它另开一条路。
        p = ev.payload
        state = p.get("state")
        if state == "asked":
            print(f"\n{C['ylw']}❓ {ev.text}{C['off']}", flush=True)
            for i, opt in enumerate(p.get("options") or [], 1):
                print(f"   {C['dim']}{i}){C['off']} {opt}", flush=True)
            if (left := p.get("remaining", -1)) >= 0:
                print(f"   {C['dim']}(还能问 {left} 次){C['off']}", flush=True)
        elif state == "answered":
            print(f"{C['grn']}✓{C['off']} {C['dim']}{p.get('answer', '')[:120]}{C['off']}", flush=True)
        elif state == "timeout":
            print(f"{C['ylw']}⏱ 无人应答 —— 它会自己判断,并把假设记进「未知与假设」{C['off']}",
                  flush=True)
        elif state == "over_budget":
            print(f"{C['ylw']}⛔ 提问额度用完,不再放行{C['off']}", flush=True)
        elif state == "declined":
            print(f"{C['dim']}↷ 已跳过{C['off']}", flush=True)
    elif ev.kind == "task":
        print(f"{C['mag']}◆ {ev.text}{C['off']}", flush=True)
    elif ev.kind == "error":
        # 合成的 API 错误:显示给人看,但它不进 StepResult.text,也不会 resume 回模型
        print(f"{C['red']}⚠ {ev.text[:200]}{C['off']}", flush=True)
    elif ev.kind == "retry":
        print(f"{C['ylw']}⟳ {ev.text}{C['off']}", flush=True)
    elif ev.kind == "reset":
        print(f"{C['ylw']}↻ {ev.text}{C['off']}", flush=True)
    elif ev.kind == "result":
        p = ev.payload
        flag = C["red"] + "失败" if p.get("is_error") else C["grn"] + "完成"
        print(
            f"{flag}{C['off']} {C['dim']}"
            f"{p.get('num_turns', 0)} 轮 / ${p.get('cost_usd', 0):.4f} / "
            f"session {str(p.get('session_id'))[:8]}{C['off']}",
            flush=True,
        )


def answer_from_stdin(channel) -> threading.Event:
    """参考实现:另起一个 daemon 线程读标准输入来回答提问。

    为什么是线程,不是 ``asyncio.to_thread``:``input()`` 阻塞时取消不掉,
    用 to_thread 的话进程退出前 asyncio 会 join 它 —— 活干完了还得按一次回车
    才能退出。daemon 线程不挡退出。

    顺带这也演示了**跨线程回答**:Web 后端、TUI 输入线程都是这个形状,
    ``channel.answer()`` 内部走 ``call_soon_threadsafe``,所以从哪个线程调都行。
    """
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            pend = channel.pending()
            if not pend:
                time.sleep(0.15)
                continue
            ask = pend[0]
            try:
                raw = input(f"{C['ylw']}你的回答{C['off']} {C['dim']}(回车=跳过,让它自己判断)"
                            f"{C['off']} > ").strip()
            except (EOFError, KeyboardInterrupt):
                channel.decline(ask.id, "输入已关闭")
                return
            if not raw:
                channel.decline(ask.id)
                continue
            # 输了个序号就当选项处理
            if ask.options and raw.isdigit() and 1 <= int(raw) <= len(ask.options):
                raw = ask.options[int(raw) - 1]
            channel.answer(ask.id, raw)

    threading.Thread(target=loop, daemon=True, name="flower-stdin").start()
    return stop


_CMDS = ("go", "run", "once")


def _with_default_cmd(argv: list[str], parser: argparse.ArgumentParser) -> list[str]:
    """`flower "帮我做一个 X"` —— 不写子命令时补上 ``go``。

    做法:从**左往右**跳过所有全局开关(以及带值开关的那个值),
    停在第一个"不属于全局开关"的 token 上 —— 它要么是子命令,要么已经是
    ``go`` 的参数,后者就在它前面插 ``go``。

    两个坑:

    * 不能用"argv 里出现过 run/once 吗"来判断 —— 诉求正文可能刚好就是那个词
      (``flower run`` 这种真歧义留给显式 ``flower go run``)。
    * 全局开关的集合**从 parser 自己派生**,不硬编码。否则以后加一个全局开关、
      忘了同步这张表,`flower --新开关 "诉求"` 就会把 ``go`` 插错位置。
      ``nargs == 0`` 的是纯开关,其余的要连值一起跳。
    """
    flags, valued = set(), set()
    for act in parser._actions:                    # argparse 没给公开 API
        for opt in act.option_strings:
            (flags if act.nargs == 0 else valued).add(opt)

    i = 0
    while i < len(argv):
        a = argv[i]
        head = a.split("=", 1)[0]
        if a in valued:
            i += 2                                  # --workspace DIR
            continue
        if a in flags or head in valued:
            i += 1                                  # -v / --workspace=DIR
            continue
        return argv if a in _CMDS else argv[:i] + ["go"] + argv[i:]
    # 走到这儿说明没有位置参数:要么空(`flower`),要么只有全局开关(`flower -v`)。
    # 补上 go,让它进交互输入 —— `ask` 是 nargs="?"。
    # 但 -h/--help 要留给 argparse,否则 `flower --help` 会变成 `flower go --help`。
    if any(a in ("-h", "--help") for a in argv):
        return argv
    return argv + ["go"]


def ask_for_prompt() -> str:
    """没在命令行给诉求时,问一句。

    为什么值得单独做:命令行里那对引号是纯负担。**实测踩过** ——
    右引号打成了中文的 `”`,zsh 一直在等真正的右引号(`dquote>` 续行提示符),
    看起来就像程序卡住了,而其实一次都没启动。这里读的是标准输入,
    不经过 shell 解析:中文引号、空格、感叹号、换行都能直接打。
    """
    if sys.stdin.isatty():
        print(f"{C['ylw']}要做什么?{C['off']} "
              f"{C['dim']}一句话就够,回车开始(Ctrl-C 退出){C['off']}", flush=True)
    try:
        ask = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        print(flush=True)
        sys.exit("已取消")
    if not ask:
        sys.exit('诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。')
    return ask


def _load(ref: str):
    """'mypkg.flows:build' 或 'flows.py:build' → 对象"""
    mod_ref, _, attr = ref.partition(":")
    if not attr:
        sys.exit("需要 模块:属性 形式,例如 flows:main")
    p = Path(mod_ref)
    if p.suffix == ".py":
        # 写了文件路径就必须真有这个文件。不然会掉进下面按模块名 import 的分支,
        # 报出来是 "No module named 'flows.py'; 'flows' is not a package" ——
        # 路径打错或在别的目录里跑的时候,这句话完全指不到问题上。
        if not p.exists():
            sys.exit(f"找不到 {p}(当前目录 {Path.cwd()})。"
                     "给的是文件路径就要能对上;要按模块名导入就别带 .py")
        sys.path.insert(0, str(p.resolve().parent))
        mod_ref = p.stem
    try:
        mod = importlib.import_module(mod_ref)
    except ModuleNotFoundError as e:
        sys.exit(f"导入 {mod_ref!r} 失败:{e}")
    if not hasattr(mod, attr):
        sys.exit(f"{mod_ref!r} 里没有 {attr!r}")
    return getattr(mod, attr)


async def _drive(wf, args, *, trim: bool | None = None) -> None:
    """跑一个 Workflow 对象。`run` 和 `go` 共用这一段。"""
    # workflow 自带工作台就用它的 —— 它把 brief/log 落在那里面,两边必须是同一个,
    # 否则确认书写在一处、注入索引扫的是另一处。见 Workflow.workbench。
    bench = getattr(wf, "workbench", None) or args.workbench
    rt = Runtime(workspace=args.workspace, run_dir=args.run_dir,
                 workbench=bench, trim=args.trim if trim is None else trim)
    stop = None
    try:
        # workflow 自己挂了提问通道 → 给它接上标准输入。
        # 通道的 on_event 由 Workflow.run 自动接到同一个出口,这里只管"谁来答"。
        if getattr(wf, "channel", None) is not None:
            if not sys.stdin.isatty():
                # 非交互(管道、nohup、CI)。不拦,但要说清楚 ——
                # 否则第一个问题被当成"输入已关闭"跳过,之后每个问题都要干等满超时。
                print(f"{C['ylw']}⚠ 标准输入不是终端,没人能回答提问。"
                      f"想让它自己判断就加 --timeout 0{C['off']}", flush=True)
            stop = answer_from_stdin(wf.channel)
        ctx = await wf.run(rt, on_event=lambda e: render(e, verbose=args.verbose))
    finally:
        if stop is not None:
            stop.set()
        rt.close()
    print(f"\n{C['dim']}总花费 ${rt.total_cost()} · 清单 {rt.run_dir/'manifest.json'}{C['off']}")
    if failed := ctx.get("_failed_at"):
        sys.exit(f"在步骤 {failed!r} 中止")


async def _run_workflow(args) -> None:
    obj = _load(args.target)
    await _drive(obj() if callable(obj) else obj, args)


async def _run_go(args) -> None:
    """零配置入口:`flower "帮我做一个 X"`。流程见 workflow/starter.py。"""
    ask = (args.ask or "").strip() or ask_for_prompt()
    try:
        wf = starter_flow(
            ask,
            workspace=args.workspace,
            isolate=args.isolate,
            clarify_only=args.clarify_only,
            max_asks=None if args.asks < 0 else args.asks,
            timeout_s=args.timeout,
            goal=not args.no_goal,
            rounds=args.rounds,
            judge_can_run=args.judge_can_run,
        )
    except ValueError as e:
        sys.exit(str(e))
    await _drive(wf, args, trim=not args.no_trim)


async def _run_once(args) -> None:
    spec = AgentSpec(
        name="ad-hoc",
        instructions=args.instructions or "",
        allowed_tools=args.tools.split(",") if args.tools else ["Read", "Glob", "Grep"],
        permission_mode=args.permission_mode,
        max_budget_usd=args.budget,
    )
    rt = Runtime(workspace=args.workspace, run_dir=args.run_dir,
                 workbench=args.workbench, trim=args.trim)
    try:
        await rt.run(
            spec, args.prompt,
            resume=args.resume, fork=args.fork,
            on_event=lambda e: render(e, verbose=args.verbose),
        )
    finally:
        rt.close()


# 全局开关。子命令是**隐形**的(`flower "诉求"` 自动补 go),所以用户不会有
# "开关要写在子命令前面"这个心理模型 —— 两个位置都得能用。做法:同一份定义
# 既加在主 parser 上,也加在每个子命令上;子命令那份 default=SUPPRESS,
# 没给就不写属性,于是不会用默认值把主 parser 已经解析出的值盖掉
# (这是 argparse 用 parents 时的经典坑)。
_GLOBALS = (
    (("-w", "--workspace"), {"default": ".", "help": "agent 的工作目录"}),
    (("-r", "--run-dir"), {"default": "runs", "help": "会话存储与运行清单"}),
    (("-v", "--verbose"), {"action": "store_true", "help": "显示思考与工具结果"}),
    (("-W", "--workbench"), {"action": "store_true",
                             "help": "启用工作台(脚本/产出/笔记落盘 + 索引注入)。"
                                     "workflow 自带 workbench 时以它为准,不必给这个"}),
    (("-T", "--trim"), {"action": "store_true",
                        "help": "resume 时把旧的大工具结果换成文件指针"}),
)


def _add_globals(parser: argparse.ArgumentParser, *, suppress: bool) -> None:
    for names, kw in _GLOBALS:
        if suppress:
            kw = {**kw, "default": argparse.SUPPRESS, "help": argparse.SUPPRESS}
        parser.add_argument(*names, **kw)


def build_parser() -> argparse.ArgumentParser:
    """单独拿出来是为了能在测试里解析而不执行(`tests/trial_offline.py`)。"""
    ap = argparse.ArgumentParser(prog="flower", description="可移植长程 agent 框架")
    _add_globals(ap, suppress=False)
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser(
        "go", help="一键跑:问清需求 → 派人干活(不写子命令时的默认)",
        epilog="全局开关(-v/-w/-r/-T)见 `flower --help`;写在诉求前面或后面都行。")
    _add_globals(g, suppress=True)
    g.add_argument("ask", nargs="?",
                   help="你的原始诉求,一句话就够。**不给就进交互输入** —— "
                        "这样不用在 shell 里加引号")
    g.add_argument("--asks", type=int, default=-1, metavar="N",
                   help="提问额度:**默认不限**(问到清楚为止)。"
                        "给个数字就是硬额度,0 = 不许提问")
    g.add_argument("--rounds", type=int, default=3, metavar="N",
                   help="干活的总轮数上限:每轮结束由独立判定者判"
                        "「做完了没有」,没达成就打回来接着做(默认 3)")
    g.add_argument("--no-goal", action="store_true",
                   help="关掉目标看守 —— 干活跑完就算完,不做判定(便宜但没有兜底)")
    g.add_argument("--judge-can-run", action="store_true",
                   help="让判定者能跑命令(判定更硬,但它就能改动工作区了)")
    g.add_argument("--timeout", type=float, default=1800.0, metavar="秒",
                   help="等你多久回答:默认 1800;0 = 全自动,不等人")
    g.add_argument("--isolate", action="store_true",
                   help="每个 subagent 分一份 git worktree(要求工作区是 git 仓库)")
    g.add_argument("--clarify-only", action="store_true", help="只问清需求,不往下干活")
    g.add_argument("--no-trim", action="store_true", help="关掉 trim(这条路径默认开)")
    g.set_defaults(fn=_run_go)

    r = sub.add_parser("run", help="运行一个 workflow")
    _add_globals(r, suppress=True)
    r.add_argument("target", help="模块:属性,例如 flows:main")
    r.set_defaults(fn=_run_workflow)

    o = sub.add_parser("once", help="跑一次单 agent")
    _add_globals(o, suppress=True)
    o.add_argument("prompt")
    o.add_argument("-i", "--instructions", help="追加在 Claude Code 原生提示词之后")
    o.add_argument("-t", "--tools", help="逗号分隔的工具白名单")
    o.add_argument("-p", "--permission-mode", default="default",
                   choices=["default", "acceptEdits", "plan", "bypassPermissions"])
    o.add_argument("-b", "--budget", type=float, help="美元预算上限")
    o.add_argument("--resume", help="续跑某个 session_id")
    o.add_argument("--fork", action="store_true", help="分叉而非续跑")
    o.set_defaults(fn=_run_once)

    return ap


def main() -> None:
    ap = build_parser()
    args = ap.parse_args(_with_default_cmd(sys.argv[1:], ap))
    load_dotenv()
    if args.verbose:
        for k, v in describe().items():
            print(f"{C['dim']}{k} = {v}{C['off']}")
    asyncio.run(args.fn(args))


if __name__ == "__main__":
    main()
