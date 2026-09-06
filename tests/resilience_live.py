"""断网 → 恢复 → 续跑,端到端实测。

这个测试会**真的**在跑到一半时把网络掐断(改 hosts 把网关指向黑洞),
观察 flower 是不是:探针挂着等 → 恢复后 resume 续上 → 错误不进上下文。

需要 sudo(改 /etc/hosts)。不给 sudo 就跳过掐网那步,只验证探针与清理。
"""
import asyncio, json, os, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flower import Runtime, Resilience, coordinator, worker, endpoint  # noqa: E402
from flower.stores.prune import is_api_error  # noqa: E402

WS = Path(__file__).resolve().parent / "_ws_res"
RUNS = Path(__file__).resolve().parent / "_runs_res"
HOSTS = "/etc/hosts"
MARK = "# flower-test"


def hosts(block: bool) -> bool:
    host, _ = endpoint()
    try:
        cur = Path(HOSTS).read_text()
        new = ("\n".join(l for l in cur.splitlines() if MARK not in l)
               + (f"\n127.0.0.1 {host} {MARK}\n" if block else "\n"))
        subprocess.run(["sudo", "-n", "tee", HOSTS], input=new, text=True,
                       capture_output=True, check=True)
        subprocess.run(["sudo", "-n", "dscacheutil", "-flushcache"], capture_output=True)
        return True
    except Exception:
        return False


async def main() -> int:
    WS.mkdir(parents=True, exist_ok=True)
    (WS / "note.txt").write_text("答案是 蓝色鲸鱼\n", encoding="utf-8")

    w = worker("读文件、做简单核对", "照做即可,别发挥。", tools=["Read", "Bash", "Glob"])
    boss = coordinator("主控", "简短完成任务。", {"执行员": w}, max_turns=10, max_budget_usd=1.0)

    rt = Runtime(workspace=WS, run_dir=RUNS, workbench=True,
                 resilience=Resilience(base_delay=2, probe_interval=5, max_offline_wait=180))
    evs = []

    async def cut_and_restore():
        await asyncio.sleep(12)
        if not hosts(True):
            print("  [无 sudo,跳过掐网]"); return
        print(f"  [{time.strftime('%H:%M:%S')}] 网络已掐断")
        await asyncio.sleep(45)
        hosts(False)
        print(f"  [{time.strftime('%H:%M:%S')}] 网络已恢复")

    try:
        task = asyncio.create_task(cut_and_restore())
        r = await rt.run(boss, "让执行员读 note.txt,把里面那个词原样告诉我。",
                         on_event=lambda e: evs.append(e))
        await task
        print(f"\nok={r.ok} attempts={r.attempts} resumed={r.resumed} "
              f"${r.cost_usd:.4f} {r.duration_s}s")
        print(f"retry 事件: {[e.text for e in evs if e.kind=='retry']}")
        print(f"error 事件: {[e.text[:70] for e in evs if e.kind=='error']}")
        print(f"回话: {r.text[:200]!r}")

        ok = True
        if any(k in r.text for k in ("ENOTFOUND", "API Error", "Can't reach")):
            print("✗ 错误文本混进了 StepResult.text"); ok = False
        else:
            print("✓ StepResult.text 干净")

        key = {"project_key": rt.project_key, "session_id": r.session_id}
        loaded = await rt.store.load(key)
        n_err = sum(is_api_error(e) for e in (loaded or []))
        print(f"✓ 喂回模型的历史里 API 错误条目: {n_err}" if n_err == 0
              else f"✗ 仍有 {n_err} 条错误消息会被 resume 回去")
        ok = ok and n_err == 0
        if r.attempts > 1:
            print(f"✓ 断线后自动重试并{'续跑' if r.resumed else '重来'}")
        return 0 if (ok and r.ok) else 1
    finally:
        hosts(False)
        rt.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
