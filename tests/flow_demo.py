"""workflow 层冒烟 —— 验证三种接法 + gate + 失败策略。

这不是给你用的 workflow,只是证明 Step/Workflow 的机制是通的。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flower import AgentSpec, Runtime, Step, Workflow  # noqa: E402

WS = Path(__file__).resolve().parent / "_ws2"
RUNS = Path(__file__).resolve().parent / "_runs2"

terse = AgentSpec(
    name="terse",
    instructions="你在测试中。回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


def build() -> Workflow:
    return Workflow([
        # 独立会话:只吃 prompt 里的东西
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # 独立会话 + 上一步结果注入 prompt(便宜,防污染)
        Step("造句", terse, lambda c: f"用「{c['取词']}」造一个五字短句,只回短句。"),
        # 续跑:同一会话,靠记忆
        Step("改写", terse, "把刚才那个短句改成疑问句,只回句子。", resume_from="造句"),
        # 分叉 + gate + 重试:复核不污染原线
        Step("复核", terse, "上面那个句子是疑问句吗?只回「是」或「否」。",
             resume_from="改写", fork=True, retries=1,
             gate=lambda r, c: "是" in r.text),
        # 条件步:前面没失败才跑
        Step("收尾", terse, "只回「完成」。", when=lambda c: "_failed_at" not in c),
    ])


async def main() -> int:
    WS.mkdir(exist_ok=True)
    (WS / "seed.txt").write_text("青花瓷\n", encoding="utf-8")

    rt = Runtime(workspace=WS, run_dir=RUNS)
    try:
        ctx = await Workflow.run(build(), rt, on_step=lambda s, r: print(
            f"  {'✓' if r.ok else '✗'} {s.name:6} "
            f"{'新会话' if not s.resume_from else ('分叉' if s.fork else '续跑'):4} "
            f"{str(r.session_id)[:8]} ${r.cost_usd:.4f} → {r.text[:40]!r}"))
    finally:
        rt.close()

    sess = ctx["_sessions"]
    print(f"\nsession 血缘:")
    for k, v in sess.items():
        print(f"  {k:6} {v[:8]}")

    ok = True
    if sess.get("改写") != sess.get("造句"):
        print("✗ resume_from 没有复用同一会话"); ok = False
    if sess.get("复核") == sess.get("改写"):
        print("✗ fork 没有分出新会话"); ok = False
    if "收尾" not in ctx:
        print("✗ when 条件步没有执行"); ok = False
    if not (RUNS / "manifest.json").is_file():
        print("✗ manifest 没落盘"); ok = False

    print(f"\n总花费 ${rt.total_cost()}")
    print("\n✓ workflow 层通过" if ok else "\n✗ workflow 层未通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
