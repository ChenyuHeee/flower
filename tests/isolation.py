"""并行 subagent 的工作区隔离 —— 三个 issue,三个 PR 分支,互不干扰。

验证的是"框架保证"而不是"提示词建议":
  * 系统提示里**没有一个字**提到 worktree / 分支 / 目录
  * 但会写代码的角色被 isolate=True 标记,hook 自动给它们各自一个 worktree
  * 只读的角色不标记,不会被加任何东西
"""
import asyncio, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flower import Runtime, coordinator, worker
from flower.core.guard import isolate_guard

WS = Path("/tmp/iso_ws")

def git(*args, cwd=WS):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True).stdout.strip()

async def main():
    injected, sub_tools = [], []

    workers = {
        "改代码": worker("修一个 bug 并提交。需要改仓库代码时找它。",
                       "你是修 bug 的。改代码、跑一下验证、git add + commit。不要 push。",
                       isolate=True),          # ← 唯一一处声明,别处再无隔离相关文字
        "看代码": worker("只读地看代码、给结论。不改任何东西。",
                       "你只读。不要写文件、不要 commit。",
                       tools=["Read", "Grep", "Glob"]),
    }

    spec = coordinator(
        "维护者",
        # 注意:这里没有任何关于 worktree / 分支 / 目录的指示
        "你在维护一个 Python 仓库。按用户给的 issue 列表派活,每个 issue 一个 subagent,并行派。",
        workers,
        max_turns=30,
        permission_mode="bypassPermissions",   # headless:没人能批准 Bash,否则 commit 做不成
    )

    rt = Runtime(workspace=WS, run_dir="runs/isolation", workbench=True, trim=True)
    # 观察注入:hook 真的动手了没有
    def on_ev(ev):
        if ev.kind == "tool" and ev.payload.get("subagent"):
            sub_tools.append(ev.payload.get("name"))

    r = await rt.run(spec,
        "仓库里 calc.py 有三个 bug:add 写成了减法、mul 写成了加法、div 没有处理除零。"
        "三个 issue 各派一个人修,并行。修完各自 commit。最后告诉我每个人在哪个目录、哪个分支、"
        "commit hash 是多少。",
        on_event=on_ev)

    print(f"\nok={r.ok} turns={r.num_turns} ${r.cost_usd:.4f} {r.duration_s}s")
    print("\n=== git worktree list ===")
    print(git("worktree", "list"))
    print("\n=== 主 checkout 的 calc.py(应当原封不动)===")
    print((WS / "calc.py").read_text().strip())
    print("\n=== 各分支的提交 ===")
    print(git("log", "--all", "--oneline", "--graph"))
    rt.close()
    return r

if __name__ == "__main__":
    asyncio.run(main())
