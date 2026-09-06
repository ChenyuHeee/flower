"""端到端冒烟 —— 证明这条链真的能跑,而不只是能 import。

验证四件事:
  1. 脱离 claude CLI:只靠 wheel 内置二进制发起真实请求
  2. 叠加式提示词:append 的指令生效,同时保留 Claude Code 原生能力
  3. 落盘:transcript 进了 SQLite
  4. 长程:resume 能续上上一轮的记忆,fork 能分叉
"""

import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flower import AgentSpec, Runtime  # noqa: E402

WS = Path(__file__).resolve().parent / "_ws"
RUNS = Path(__file__).resolve().parent / "_runs"


async def main() -> int:
    # 每次从干净状态起跑:断言的是"这一轮产生了 2 个 session",
    # 留着上一轮的库会让计数累加,第二次跑必挂。
    shutil.rmtree(RUNS, ignore_errors=True)
    WS.mkdir(exist_ok=True)
    (WS / "canary.txt").write_text("紫色犀牛\n", encoding="utf-8")

    spec = AgentSpec(
        name="smoke",
        instructions="你在冒烟测试中。回答务必极简,不解释,不寒暄。",
        allowed_tools=["Read", "Glob"],
        max_turns=6,
    )
    rt = Runtime(workspace=WS, run_dir=RUNS)
    ok = True
    try:
        # 1+2+3 —— 真实请求 + 工具调用 + 落盘
        r1 = await rt.run(spec, "读 canary.txt,只回文件里那个词。")
        print(f"[1] ok={r1.ok} turns={r1.num_turns} ${r1.cost_usd:.4f} "
              f"{r1.duration_s}s session={str(r1.session_id)[:8]}")
        print(f"    → {r1.text[:120]!r}")
        if not r1.ok:
            print("    错误:", r1.error); return 1
        if "紫色犀牛" not in r1.text:
            print("    ✗ 没读到文件内容,工具链可能没通"); ok = False

        entries = await rt.store.load({"project_key": rt.project_key, "session_id": r1.session_id})
        print(f"[3] SQLite 落盘 {len(entries or [])} 条")
        if not entries:
            print("    ✗ transcript 没进库"); ok = False

        # 4a —— resume:不再提文件,靠会话记忆
        r2 = await rt.run(spec, "把刚才那个词倒着写。", resume=r1.session_id)
        print(f"[4a] resume ok={r2.ok} session={str(r2.session_id)[:8]} → {r2.text[:60]!r}")
        if not r2.ok or "犀" not in r2.text:
            print("    ✗ resume 没续上上下文"); ok = False

        # 4b —— fork:从 r1 分叉,不污染原线
        r3 = await rt.run(spec, "那个词是几个字?只回数字。", resume=r1.session_id, fork=True)
        print(f"[4b] fork  ok={r3.ok} session={str(r3.session_id)[:8]} → {r3.text[:60]!r}")
        if r3.session_id == r1.session_id:
            print("    ✗ fork 没有分出新 session"); ok = False

        sess = await rt.store.list_sessions(rt.project_key)
        print(f"\n[5] project_key={rt.project_key}")
        print(f"    库里 {len(sess)} 个 session,总花费 ${rt.total_cost()}")
        if len(sess) != 2:
            print("    ✗ 期望 2 个 session(原线 + 分叉)"); ok = False
    finally:
        rt.close()

    print("\n✓ 冒烟通过" if ok else "\n✗ 冒烟未通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
