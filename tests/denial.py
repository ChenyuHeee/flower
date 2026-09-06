"""被拒的工具调用不该常驻上下文 —— 以及摘除时链不能断。

被拒调用是纯粹的负价值:它没执行过,结果里只有一句"你不该这么做"(这条规矩
system prompt 里已经有了),却要占约 273 字符(实测:93 字拒绝语 + 180 字**死命令原文**)。
更糟的是它会把模型教成"反正会被拦",连放行的命令都不再尝试。

结构性红线:摘掉 tool_use 就必须同时摘掉它的 tool_result(反之亦然),
且 parentUuid 链必须重新接上 —— 断链会丢掉断点之前的全部历史。
"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flower.stores.prune import PruningSessionStore, PrunePolicy, is_denial
from flower.stores.trim import EphemeralPolicy


def audit(rows, label=""):
    """tool_use / tool_result 必须一一配对;parentUuid 必须连通。"""
    uses, results = set(), set()
    for e in rows:
        c = (e.get("message") or {}).get("content")
        if not isinstance(c, list):
            continue
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                uses.add(b["id"])
            if b.get("type") == "tool_result":
                results.add(b["tool_use_id"])
    uuids = {e["uuid"] for e in rows if e.get("uuid")}
    broken = [e["uuid"] for e in rows if e.get("parentUuid") and e["parentUuid"] not in uuids]
    bad = (results - uses, uses - results, broken)
    if any(bad):
        print(f"  ✗ {label} 孤儿结果{sorted(bad[0])} 孤儿调用{sorted(bad[1])} 断链{bad[2]}")
    return not any(bad)


def store(keep):
    return PruningSessionStore(":memory:", workspace="/tmp",
                               prune=PrunePolicy(keep_denials=keep),
                               ephemeral=EphemeralPolicy(enabled=False))


def transcript():
    """两次被拒(t2/t4)+ 一次正常(t1),被拒的**夹在中间** —— 末尾的话不暴露断链。"""
    def denial(uid, parent, tid):
        return {"uuid": uid, "parentUuid": parent, "type": "user",
                "toolDenialKind": "permission-rule",
                "toolUseResult": "Error: 协调者不直接使用 Bash。",
                "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": tid,
                     "content": "协调者不直接使用 Bash。用 Agent 工具派一个 subagent 去做。",
                     "is_error": True}]}}
    return [
        {"uuid": "a1", "parentUuid": None, "type": "assistant", "message": {"role": "assistant",
            "content": [{"type": "text", "text": "先看一眼"},
                        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "git status"}},
                        {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "pytest -q"}}]}},
        {"uuid": "u1", "parentUuid": "a1", "type": "user", "message": {"role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "On branch main"}]}},
        denial("u2", "u1", "t2"),
        {"uuid": "a2", "parentUuid": "u2", "type": "assistant", "message": {"role": "assistant",
            "content": [{"type": "tool_use", "id": "t4", "name": "Write", "input": {"file_path": "x.py"}}]}},
        denial("u3", "a2", "t4"),
        {"uuid": "a3", "parentUuid": "u3", "type": "assistant",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "那我派人"}]}},
    ]


def main():
    ok = True
    ents = transcript()
    print(f"原始 {len(ents)} 条,被拒 {sum(1 for e in ents if is_denial(e))} 次")
    ok &= audit(ents, "原始")

    for keep, want in ((0, 0), (1, 1), (5, 2)):
        st = store(keep)
        out = st.prune(ents)
        left = sum(1 for e in out if is_denial(e))
        good = audit(out, f"keep={keep}")
        hit = left == want
        ok &= good and hit
        print(f"  keep_denials={keep}: {len(ents)}→{len(out)} 条,摘 {st.denials_dropped} 次,"
              f"剩 {left} 次(期望 {want}) {'✓' if good and hit else '✗'}")

    # 正常的那次调用(t1)绝不能被误伤 —— 同一条 assistant 消息里混着被拒的 t2
    out = store(0).prune(ents)
    kept = [b["id"] for e in out for b in ((e.get("message") or {}).get("content") or [])
            if isinstance(b, dict) and b.get("type") == "tool_use"]
    if kept != ["t1"]:
        print(f"  ✗ 同消息内误伤:剩下 {kept},应当只剩 t1"); ok = False
    else:
        print("  ✓ 同一条消息里只摘被拒的块,正常调用留下")

    # 拒绝语在 toolUseResult 里还存了一份,也得清掉
    if any("协调者不直接" in str(e.get("toolUseResult", "")) for e in out):
        print("  ✗ toolUseResult 里仍残留拒绝语"); ok = False
    else:
        print("  ✓ toolUseResult 里的副本一并清掉")

    # 断线残渣走同一条 relink 路径:错误在**中间**时历史不能丢
    mid = [
        {"uuid": "m1", "parentUuid": None, "type": "user", "message": {"role": "user", "content": "第一轮"}},
        {"uuid": "e1", "parentUuid": "m1", "type": "assistant", "isApiErrorMessage": True,
         "message": {"role": "assistant", "model": "<synthetic>",
                     "content": [{"type": "text", "text": "API Error: ENOTFOUND"}]}},
        {"uuid": "m2", "parentUuid": "e1", "type": "assistant",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "继续"}]}},
    ]
    out = store(1).prune(mid)
    if len(out) != 2 or not audit(out, "断线残渣"):
        print(f"  ✗ 断线残渣:{len(out)} 条"); ok = False
    else:
        print("  ✓ 断线残渣摘除后链仍连通(错误在中间也不丢历史)")

    print("\n" + ("✓ 被拒调用清理通过" if ok else "✗ 未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
