"""协调者 / 执行者 分工的实测 —— 这一整套架构就压在一个事实上:

    subagent 的工具调用和试错,进的是**它自己的 transcript**,不进主线程上下文。

如果这条不成立,"主 agent 只装决策"就是空话。所以这里直接量:
一次会产生大量工具输出的任务,跑完之后主 transcript 有多大、subagent transcript 有多大。
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flower import Runtime, coordinator, worker  # noqa: E402

WS = Path(__file__).resolve().parent / "_ws_deleg"
RUNS = Path(__file__).resolve().parent / "_runs_deleg"


def size(entries) -> int:
    return len(json.dumps(entries or [], ensure_ascii=False))


async def main() -> int:
    (WS / "data").mkdir(parents=True, exist_ok=True)
    # 三个大文件:任何认真读它们的 agent 都会拿到几万字符的工具结果
    for i, n in enumerate([600, 900, 400]):
        (WS / "data" / f"f{i}.txt").write_text(
            "".join(f"{i}-{j:04d} " + "x" * 60 + "\n" for j in range(n)), encoding="utf-8")

    analyst = worker(
        "分析文件内容:统计、查找、比对。需要真读文件、跑命令的活都派给它。",
        "你负责在 data/ 下做文本分析。用命令行完成,不要手工估算。",
        tools=["Read", "Write", "Bash", "Glob", "Grep"],
    )
    boss = coordinator(
        "主控",
        "目标:摸清 data/ 下三个文件的规模。做完给一句话结论。",
        {"分析员": analyst},
        max_turns=14,
        max_budget_usd=1.5,
    )

    rt = Runtime(workspace=WS, run_dir=RUNS, workbench=True)
    denied, spawned, glanced = [], [], []

    def on_event(ev):
        # 只统计主线程的工具调用 —— subagent 的调用也走同一条事件流
        if ev.kind == "tool_call" and not ev.payload.get("subagent"):
            spawned.append(ev.tool)
            if ev.tool == "Bash":
                # glance 默认开着,Bash 出现在协调者工具表里是对的。
                # 但放行的必须只是"看一眼" —— 动手的活照样得派人。
                glanced.append((ev.payload.get("input") or {}).get("command", ""))
        if ev.kind == "tool_result" and "协调者不直接使用" in ev.text:
            denied.append(ev.text[:60])

    try:
        r = await rt.run(boss, "统计 data/ 下每个 .txt 的行数和总字符数,告诉我哪个最大。",
                         on_event=on_event)
        print(f"ok={r.ok} turns={r.num_turns} ${r.cost_usd:.4f} {r.duration_s}s")
        print(f"主 agent 用过的工具: {sorted(set(spawned))}")
        # SendMessage 是 harness 随 Agent 一起给的:给已经派出去的 subagent 追加消息。
        # 它是"派活"的一种,不是动手 —— 而且比重新派一个便宜(省一次约 4.3k 启动)。
        assert set(spawned) <= {"Agent", "SendMessage", "TodoWrite", "Read", "Bash"}, \
            f"协调者动手了: {set(spawned)}"
        # 协调者的 Bash 只能是无副作用的查看命令 —— 和剪枝表同源。
        from flower.stores.trim import is_ephemeral
        bad = [c for c in glanced if not is_ephemeral(c)]
        assert not bad, f"协调者跑了会改状态的命令: {bad}"
        if glanced:
            print(f"协调者自己看了 {len(glanced)} 次(都无副作用): {glanced[0][:70]!r}")
        print(f"被 guard 拦下的自己动手: {len(denied)} 次 {denied[:2]}")
        print(f"回话({len(r.text)} 字符): {r.text[:300]!r}")
        if not r.ok:
            print("错误:", r.error)
            return 1

        key = {"project_key": rt.project_key, "session_id": r.session_id}
        main_entries = await rt.store.load(key)
        subs = await rt.store.list_subkeys(key)
        main_sz = size(main_entries)
        sub_total = 0
        print(f"\n主 transcript : {len(main_entries or [])} 条, {main_sz:,} 字符")
        for sp in subs:
            e = await rt.store.load({**key, "subpath": sp})
            sub_total += size(e)
            print(f"  └ {sp}: {len(e or [])} 条, {size(e):,} 字符")
        print(f"subagent 合计 : {sub_total:,} 字符")

        if not subs:
            print("\n✗ 没有 subagent transcript —— 协调者没派活,或 Agent 工具名不对")
            return 1
        share = sub_total / (sub_total + main_sz)
        print(f"\n沉到 subagent 的比例: {share:.0%}")
        wb = rt.workbench
        print(f"工作台 spill 文件: {len(list((wb.root/'spill').glob('*.txt')))} 个")
        print("判定:", "✓ 重活确实在 subagent 里" if share > 0.5 else "✗ 主线程仍然背着大量细节")
        return 0 if share > 0.5 else 1
    finally:
        rt.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
