"""从一次运行的 sessions.db 里量出真相 —— 不发请求,纯读。

    python tools/analyze_run.py <run_dir>

为什么需要它:`manifest.json` 只有一行总账,而 transcript 里每条 assistant 消息
都带完整 `usage`(输入/输出/cache 命中/cache 创建,连 thinking_tokens 都分开)。
这个粒度能回答 manifest 回答不了的问题:

  * 上下文经济学到底成立到什么程度 —— 主线程 vs subagent 的分布
  * **主线程的上下文增长曲线** —— 长程运行最关键的那条线。每条 assistant 消息的
    `input_tokens + cache_read_input_tokens` 就是那一轮的上下文规模
  * 钱花在哪 —— 主线程还是 subagent,cache 命中率多少
  * 各种剪枝机制实际触发了多少次
  * 协调者自己跑了多少 Bash、被拒了多少次

用法上它对任何 flower 运行都通用,不只 HT001。
"""

from __future__ import annotations

import collections
import json
import re
import sqlite3
import sys
from pathlib import Path


def load(db: Path) -> dict[str, list[dict]]:
    """按 store_key 分组读出所有条目。只读打开,不碰正在跑的库。"""
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    out: dict[str, list[dict]] = collections.defaultdict(list)
    for key, payload in c.execute("select store_key, payload from entries order by store_key, seq"):
        try:
            out[key].append(json.loads(payload))
        except Exception:
            pass
    c.close()
    return out


def blocks(entry: dict):
    ct = (entry.get("message") or {}).get("content")
    if isinstance(ct, list):
        for b in ct:
            if isinstance(b, dict):
                yield b
    elif isinstance(ct, str):
        yield {"type": "text", "text": ct}


def chars(x) -> int:
    if x is None:
        return 0
    return len(x if isinstance(x, str) else json.dumps(x, ensure_ascii=False))


def usage_of(e: dict) -> dict:
    return ((e.get("message") or {}).get("usage")) or {}


def ctx_size(u: dict) -> int:
    """那一轮模型实际看到的上下文规模。

    cache_read 是命中缓存的部分,cache_creation 是这一轮新写进缓存的部分 ——
    两者都在上下文里,都要算。只看 input_tokens 会严重低估(缓存命中时它接近 0)。
    """
    return (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
            + u.get("cache_creation_input_tokens", 0))


def human(n: float) -> str:
    for unit in ("", "K", "M"):
        if abs(n) < 1000:
            return f"{n:.1f}{unit}" if unit else f"{n:.0f}"
        n /= 1000
    return f"{n:.1f}B"


def main(run_dir: str) -> int:
    rd = Path(run_dir).expanduser()
    db = rd / "sessions.db"
    if not db.is_file():
        print(f"找不到 {db}")
        return 1

    data = load(db)
    main_keys = [k for k in data if "subagent" not in k]
    sub_keys = [k for k in data if "subagent" in k]

    # ---------- 账 ----------
    man = rd / "manifest.json"
    steps = json.loads(man.read_text(encoding="utf-8")) if man.is_file() else []
    total_usd = sum(s.get("cost_usd", 0) for s in steps)

    print("=" * 72)
    print(f"运行目录 {rd}")
    if steps:
        print(f"步骤 {len(steps)} 个,合计 ${total_usd:.4f}")
        for s in steps:
            dur = s.get("duration_s") or (s.get("ended_at", 0) - s.get("started_at", 0))
            print(f"  {s['step']:<12} ${s['cost_usd']:>9.4f}  {s['num_turns']:>3}轮  "
                  f"attempts={s['attempts']}  resumed={s['resumed']}  {dur/3600:.2f}h")

    # ---------- 上下文经济学 ----------
    def agg(keys):
        t = collections.Counter()
        for k in keys:
            for e in data[k]:
                u = usage_of(e)
                if u:
                    t["turns"] += 1
                    t["in"] += u.get("input_tokens", 0)
                    t["cache_read"] += u.get("cache_read_input_tokens", 0)
                    t["cache_new"] += u.get("cache_creation_input_tokens", 0)
                    t["out"] += u.get("output_tokens", 0)
                    t["think"] += (u.get("output_tokens_details") or {}).get("thinking_tokens", 0)
                t["chars"] += sum(chars(b.get("text")) + chars(b.get("input"))
                                  + chars(b.get("content")) for b in blocks(e))
                t["entries"] += 1
        return t

    m, s_ = agg(main_keys), agg(sub_keys)
    print("\n" + "=" * 72)
    print("【上下文经济学】主线程 vs subagent")
    print(f"  {'':16}{'主线程':>14}{'subagent':>14}{'subagent 占比':>16}")
    for label, key in (("条目数", "entries"), ("模型轮次", "turns"),
                       ("正文字符", "chars"), ("输出 token", "out")):
        a, b = m[key], s_[key]
        pct = f"{b/(a+b)*100:.1f}%" if (a + b) else "-"
        print(f"  {label:<14}{human(a):>14}{human(b):>14}{pct:>16}")
    print(f"  subagent 数量:{len(sub_keys)}")

    # ---------- 主线程上下文曲线 ----------
    curve = []
    for k in main_keys:
        for e in data[k]:
            u = usage_of(e)
            if u:
                curve.append(ctx_size(u))
    if curve:
        print("\n" + "=" * 72)
        print("【主线程上下文增长曲线】每一轮模型实际看到多少 token")
        print(f"  轮数 {len(curve)}  最小 {human(curve[0])}  最大 {human(max(curve))}  "
              f"最后一轮 {human(curve[-1])}")
        peak = max(curve)
        for i in range(0, len(curve), max(1, len(curve) // 20)):
            bar = "█" * int(curve[i] / peak * 44)
            print(f"  第{i+1:>3}轮 {human(curve[i]):>7} |{bar}")
        # 有没有回落 —— 回落说明发生了压缩或剪枝
        drops = [(i, curve[i - 1], curve[i]) for i in range(1, len(curve))
                 if curve[i] < curve[i - 1] * 0.7]
        print(f"  **显著回落(降到前一轮 70% 以下)**:{len(drops)} 次" +
              ("" if not drops else f" —— 第 {[d[0]+1 for d in drops][:6]} 轮"))

    # ---------- 缓存 ----------
    tot_ctx = m["in"] + m["cache_read"] + m["cache_new"] + s_["in"] + s_["cache_read"] + s_["cache_new"]
    hit = m["cache_read"] + s_["cache_read"]
    print("\n" + "=" * 72)
    print("【缓存】cache 命中省下的钱是长程运行的关键")
    print(f"  总输入 {human(tot_ctx)} token,其中命中缓存 {human(hit)}"
          f"({hit/tot_ctx*100:.1f}%),新建缓存 {human(m['cache_new']+s_['cache_new'])},"
          f"未缓存 {human(m['in']+s_['in'])}")
    print(f"  输出 {human(m['out']+s_['out'])} token"
          f"(其中 thinking {human(m['think']+s_['think'])})")

    # ---------- 工具使用 ----------
    DENY = "协调者不直接使用"
    for label, keys in (("主线程", main_keys), ("subagent", sub_keys)):
        calls = collections.Counter()
        bash_cmds = []
        denied = 0
        pend = {}
        for k in keys:
            for e in data[k]:
                for b in blocks(e):
                    if b.get("type") == "tool_use":
                        nm = b.get("name", "?")
                        calls[nm] += 1
                        pend[b.get("id")] = nm
                        if nm == "Bash":
                            cmd = (b.get("input") or {}).get("command", "")
                            bash_cmds.append(cmd)
                    elif b.get("type") == "tool_result":
                        t = b.get("content")
                        txt = t if isinstance(t, str) else json.dumps(t, ensure_ascii=False)
                        if DENY in (txt or ""):
                            denied += 1
        print("\n" + "=" * 72)
        print(f"【{label}的工具使用】共 {sum(calls.values())} 次")
        for nm, n in calls.most_common(10):
            print(f"  {nm:<16}{n:>6}")
        print(f"  **被拒(协调者动手被拦)**:{denied} 次" +
              (f" → 拒绝率 {denied/sum(calls.values())*100:.1f}%" if calls else ""))
        if bash_cmds and label == "主线程":
            head = collections.Counter(re.split(r"\s+", c.strip())[0] for c in bash_cmds if c.strip())
            print(f"  协调者自己跑的 Bash 首词分布:{dict(head.most_common(8))}")

    # ---------- 落盘与剪枝 ----------
    wb = rd.parent / ".flower"
    print("\n" + "=" * 72)
    print("【落盘】大结果换成路径指针")
    spill = wb / "spill"
    if spill.is_dir():
        fs = list(spill.glob("*"))
        tot = sum(f.stat().st_size for f in fs if f.is_file())
        print(f"  spill {len(fs)} 次,落盘 {human(tot)} 字符 —— 这些没有常驻上下文")
    for sub in ("scripts", "artifacts", "notes"):
        d = wb / sub
        if d.is_dir():
            fs = [f for f in d.rglob("*") if f.is_file()]
            print(f"  {sub:<10}{len(fs):>4} 个  {human(sum(f.stat().st_size for f in fs))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "runs"))
