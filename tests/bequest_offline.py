"""给下一个工具的交接(CLAUDE.md / AGENTS.md)—— 离线验证。**不打网络,不花钱。**

钉住 issue #24 的纯逻辑(模型真去写那一轮是 live,不在这里):

  1. 解析:五段;complete() 只要求「这是什么」+「工作台」
  2. **受管块三情形**:新建 / 追加不覆盖用户内容 / 重跑只替换块内(安全项)
  3. 一份内容两个名字:CLAUDE.md + AGENTS.md
  4. 机械兜底:模型没写成 → 降级件照样落盘,带标记
  5. novel 回归:「正文.md 由 merge_manuscript.py 从 artifacts/ 合成,别直接改」这条
     一旦模型写进 generated 段,就必须原样落进文件
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flower.core.bequest import (BEGIN, END, Bequest, mechanical,     # noqa: E402
                                 write_both, write_managed)

ok = True


def check(cond, msg):
    global ok
    print(f"  {'✓' if cond else '✗'} {msg}")
    if not cond:
        ok = False


# 模型可能输出的样子(注意 novel 的那条生成物知识)
MODEL_OUT = """\
先随便说一句无关的话。

## 这是什么
一本长篇小说的重写项目,把旧稿按新大纲重排。

## 验收:达成与未达成
20 章全部重写完成;**第 11 章的评审必改项还没落实**(派工漏洞掉在地上)。

## 哪些文件是生成的、由什么生成
`artifacts/正文.md` 由 `scripts/merge_manuscript.py` 从 `artifacts/` 下各分组稿件合成 ——
**别直接改 正文.md**,改对应的分组稿再重新合。第 11 章的有效稿在 `ch11-rewrite.md`
(作废的 `ch11-14.md` 反而 mtime 更新,按时间戳猜必错)。

## 走不通的路
试过按 mtime 自动选最新稿,不行:作废稿反而更新。只能按 SOURCES 显式指派。

## 工作台在哪、怎么读
.flower/notes/ 有需求、大纲、决策;artifacts/ 是产出;scripts/ 是合并脚本。先读 notes/决策-*.md。
"""

NOVEL_FACT = "正文.md"
NOVEL_SRC = "merge_manuscript.py"


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="flower-bequest-"))

    print("\n[1] 解析:五段各就各位;complete() 只要求「这是什么」+「工作台」")
    b = Bequest.parse(MODEL_OUT)
    check("长篇小说" in b.what, "这是什么")
    check("没落实" in b.acceptance or "没达成" in b.acceptance or "未" in b.acceptance
          or "还没" in b.acceptance, "验收(含未达成)")
    check(NOVEL_FACT in b.generated and NOVEL_SRC in b.generated, "生成物段抓到了 正文.md 由脚本合成")
    check("mtime" in b.deadends or "作废" in b.deadends, "走不通的路")
    check("notes" in b.workbench, "工作台")
    check(b.complete(), "五段齐 → complete")
    check("先随便说一句无关的话" not in (b.what + b.generated), "段落之外的闲话没漏进来")
    thin = Bequest(what="有", workbench="")
    check(not thin.complete() and "工作台" in "".join(thin.missing()), "缺工作台 → 不完整")
    check(Bequest(what="有", workbench="去 notes/").complete(),
          "必填只有那两段 —— 硬要求生成物/死路非空会逼编造(可能真为空)")

    print("\n[2] block_body 能被原样解析回来(round-trip)")
    b2 = Bequest.parse(b.block_body())
    check(NOVEL_FACT in b2.generated and "长篇小说" in b2.what, "受管块正文解析回五段,不丢内容")
    check(b.block_body().count("正文.md") >= 1, "生成物那条在正文里")

    print("\n[3] 受管块:文件不存在 → 新建,只有受管块")
    d = tmp / "fresh"
    p = write_managed(d / "CLAUDE.md", b.block_body())
    txt = p.read_text(encoding="utf-8")
    check(BEGIN in txt and END in txt, "带上了 begin/end 标记")
    check(NOVEL_FACT in txt, "内容进去了")

    print("\n[4] 受管块:文件已存在(用户自己的 CLAUDE.md)→ 原内容一字不动,块追加在后")
    d2 = tmp / "existing"
    d2.mkdir()
    user = "# 我的项目约定\n\n- 用 4 空格缩进\n- 提交信息用祈使句\n"
    (d2 / "CLAUDE.md").write_text(user, encoding="utf-8")
    write_managed(d2 / "CLAUDE.md", b.block_body())
    txt2 = (d2 / "CLAUDE.md").read_text(encoding="utf-8")
    check(user.strip() in txt2, "**用户原内容一字不动**(4 空格缩进那两条还在)")
    check(txt2.index("我的项目约定") < txt2.index(BEGIN), "用户内容在前,受管块在后")
    check(NOVEL_FACT in txt2, "flower 的部分在受管块里")

    print("\n[5] 重跑幂等:只替换块内,用户内容(块前 + 块后)都不动")
    # 用户在块**后面**也加了东西,重跑不能吃掉
    txt2b = txt2.rstrip() + "\n\n## 我后来加的一节\n\n随手记点东西\n"
    (d2 / "CLAUDE.md").write_text(txt2b, encoding="utf-8")
    b_new = Bequest(what="更新后的描述", workbench="去 notes/ 看", generated="新的生成物说明 X.md")
    write_managed(d2 / "CLAUDE.md", b_new.block_body())
    t3 = (d2 / "CLAUDE.md").read_text(encoding="utf-8")
    check(t3.count(BEGIN) == 1 and t3.count(END) == 1, "还是只有一对标记(没有越堆越多)")
    check("我的项目约定" in t3 and "我后来加的一节" in t3, "块前、块后的用户内容都留住了")
    check("更新后的描述" in t3 and NOVEL_FACT not in t3, "块内被换成新内容(旧的 正文.md 段没了)")
    # 再跑一次同样的,内容应当稳定(真幂等)
    write_managed(d2 / "CLAUDE.md", b_new.block_body())
    check((d2 / "CLAUDE.md").read_text(encoding="utf-8") == t3, "同内容重跑 → 文件逐字节不变(幂等)")

    print("\n[6] 一份内容,两个名字:CLAUDE.md + AGENTS.md")
    d3 = tmp / "both"
    paths = write_both(d3, b.block_body())
    names = sorted(p.name for p in paths)
    check(names == ["AGENTS.md", "CLAUDE.md"], f"两个都写了:{names}")
    a, c = (d3 / "AGENTS.md").read_text(encoding="utf-8"), (d3 / "CLAUDE.md").read_text(encoding="utf-8")
    check(a == c, "两个文件内容完全一致")
    check(NOVEL_FACT in a, "novel 那条生成物知识两边都在")

    print("\n[7] 机械兜底:模型没写成 → 降级件照样落盘,明确标注")
    m = mechanical(what="做一个 md→html 小工具", why="模型没回话")
    check(m.degraded, "带降级标记")
    check(m.complete(), "降级件本身完整(能落盘)")
    d4 = tmp / "degraded"
    pm = write_both(d4, m.block_body())
    tm = pm[0].read_text(encoding="utf-8")
    check("降级" in tm and "md→html" in tm, "降级件落了盘,含标记和已知的一句需求")
    check("notes" in tm and "别直接改" in tm, "至少把接手的人指向工作台、提醒别改生成物")

    print("\n[8] novel 回归:生成物那条一旦写进,必须原样落进文件")
    d5 = tmp / "novel"
    write_both(d5, Bequest.parse(MODEL_OUT).block_body())
    tn = (d5 / "CLAUDE.md").read_text(encoding="utf-8")
    check(NOVEL_FACT in tn and NOVEL_SRC in tn and "别直接改" in tn,
          "「正文.md 由 merge_manuscript.py 合成,别直接改」原样落进 CLAUDE.md")

    print(f"\n{'✓ 给下一个工具的交接全部通过' if ok else '✗ 有失败'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
