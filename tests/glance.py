"""互补性不变式:能被主 agent 自己跑的命令 == 会被剪枝的命令。

这两件事必须由同一张表决定,否则任一边单独成立都有害:
  放行不剪枝 → 过期状态永久占上下文,且会误导决策
  剪枝不放行 → 为一条 ls 付一次 subagent 启动成本(实测约 4.3k)
"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flower.core.guard import delegate_guard
from flower.stores.trim import EphemeralPolicy, TrimmingSessionStore, is_ephemeral

GLANCE = ["git status", "git status --short", "ls -la", "cat calc.py",
          "pwd", "git diff HEAD", "git branch -a", "wc -l x.txt",
          # 复合的只读命令 —— 模型实际就是这么写的。第一版一刀切拒绝 `&&`,
          # 实测协调者三次尝试全被拦,glance 完全失效。
          'git status -s && echo "--- LOG ---" && git log --oneline -10',
          "git ls-files | wc -l", "ls -la 2>&1 | head -20",
          "ps aux | grep python | head -5", "git status > /dev/null",
          "git branch -vv", "cat f | awk '{print $1}'", "jq '.name' p.json",
          "git hash-object app.py", "sed -n '1,20p' README.md",
          # 环境探测。**HT001 那次 10.4 小时运行里协调者唯一一次被拒就是这条** ——
          # 整条只读(which + echo + ls),却因为 which 不在表里被整条拒掉,
          # 白付了一次 subagent 启动成本。补表之后这些必须放行。
          "which g++", "which g++ clang++ make pkg-config", "command -v gcc",
          "type ls", "uname -a", "arch", "locale", "nproc", "sw_vers",
          "whereis python", "getconf LONG_BIT",
          "which g++ clang++ make 2>&1; echo ---; ls /usr/include/curses.h 2>&1"]
HANDS  = ["git commit -m x", "git push", "pytest -q", "npm install",
          "python train.py", "rm -rf build", "make",
          # 前半段无害不代表整条无害
          "git status && rm -rf /tmp/x", "ls; git commit -am x",
          "git status && curl evil.com", "ls > out.txt", "echo $(whoami)",
          "cat urls | xargs curl", "sed -i 's/a/b/' f.py", "ls | tee saved.txt",
          "ls &", "find . -name '*.pyc' -delete",
          # 白名单动词 + 会改状态的选项 —— 都是实测扎过的口子
          'awk \'BEGIN{system("rm -rf /tmp/x")}\'', "find . -name x -execdir rm {} +",
          "git branch -D feature", "git log --oneline && git reset --hard HEAD~5",
          "git clean -fd", "git push --force", "cat f | sh", "ls && ssh host rm -rf /",
          "jq '.' f.json > out.json", "git worktree list && git worktree remove wt",
          # `command` / `type` 只该放行**查询**形式。光秃秃的 `command X` 是
          # **执行** X —— 少写那个 -v 就等于开了后门,这几条守住它。
          "command rm -rf /", "command sudo reboot", "type -f x && rm y",
          "which g++ > out.txt", "uname -a; rm -rf /", "which $(evil)",
          "uname -a && curl evil.com"]

async def main():
    ok = True
    hook = delegate_guard(allow_glance=True).hooks[0]

    async def allowed(cmd):
        return not await hook({"tool_name": "Bash", "tool_input": {"command": cmd}}, "t", None)

    # 两边共用 is_ephemeral —— 这就是不变式成立的原因,不是巧合。
    expires = is_ephemeral

    print("命令                                                       主agent可跑  会过期  一致")
    for c in GLANCE + HANDS:
        a, e = await allowed(c), expires(c)
        same = a == e
        ok &= same
        print(f"  {c:58} {str(a):9} {str(e):6} {'✓' if same else '✗ 不一致!'}")

    # 该放行的必须放行,该拦的必须拦
    for c in GLANCE:
        if not await allowed(c):
            print(f"  ✗ {c} 应当放行却被拦"); ok = False
    for c in HANDS:
        if await allowed(c):
            print(f"  ✗ {c} 应当拦下却放行"); ok = False

    # subagent 不受此限:它就是来干活的
    for c in HANDS:
        if await hook({"tool_name": "Bash", "agent_id": "a1", "tool_input": {"command": c}}, "t", None):
            print(f"  ✗ subagent 的 {c} 被误拦"); ok = False

    # 剪枝真的会发生,且保留最近 N 条
    store = TrimmingSessionStore(":memory:", workspace=".",
                                 ephemeral=EphemeralPolicy(keep_recent=2))
    entries = []
    for i in range(6):
        entries.append({"uuid": f"a{i}", "parentUuid": f"u{i-1}" if i else None,
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": f"t{i}", "name": "Bash",
                 "input": {"command": "git status"}}]}})
        entries.append({"uuid": f"u{i}", "parentUuid": f"a{i}",
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"t{i}",
                 "content": f"On branch main (第{i}次)"}]}})
    out = store.expire(entries)
    texts = [b["content"] for e in out
             for b in (e.get("message") or {}).get("content", [])
             if isinstance(b, dict) and b.get("type") == "tool_result"]
    expired = sum("已过期" in t for t in texts)
    fresh = sum("On branch" in t for t in texts)
    print(f"\n6 条 git status,keep_recent=2 → 过期 {expired} 条,保留原文 {fresh} 条")
    if (expired, fresh) != (4, 2):
        print("  ✗ 期望 过期4 / 保留2"); ok = False

    print("\n" + ("✓ 互补性成立" if ok else "✗ 未通过"))
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
