"""模板 —— 照这个形状写你自己的 `flows.py`。

**想直接试用不需要这个文件**:`flower "帮我做一个 X"` 跑的就是同样的两步流程
(实现在 `flower/workflow/starter.py`)。这个文件的用处是给你抄:
把下面两步换成你自己的步骤,然后

    flower run flows.py:main

领域流程是你的活,框架只管"一步怎么跑、步与步之间怎么接"。

自己接线时容易漏的三处,下面用 ① ② ③ 标出来了 —— 漏了都**不报错**,
只是确认书悄悄进不了下游 agent 的视野。理由见 docs/workflow.md。
"""

from pathlib import Path

from flower import (HumanChannel, Step, Workbench, Workflow,
                    clarify_step, coordinator, worker)

ASK = "帮我做一个 X"          # ← 换成你的诉求。一句话就够,要问什么由确认者决定


def main() -> Workflow:
    # ① 工作台自己建。开 worktree 隔离时要传 home= 指到仓库外,
    #    否则被隔离的 agent 写不进这个共享层(见 Workbench 文档字符串)。
    wb = Workbench(Path.cwd()).ensure()

    ch = HumanChannel(log_path=wb.notes / "问答记录.md", max_asks=6, timeout_s=1800)

    coord = coordinator("协调者", "", {
        "coder": worker("写代码与测试。要动手实现的活派给它。",
                        "你负责实现。每改一处就跑一次验证,别攒到最后。"),
    })

    return Workflow(
        # ② channel 和 workbench 都挂上 —— 驱动程序靠这两个字段发现:
        #    前者决定"谁来回答提问",后者决定"Runtime 用哪个工作台"。
        channel=ch,
        workbench=wb,
        steps=[
            # ③ brief 落在 wb.notes 里。工作台索引会注入每个 agent 的 system prompt,
            #    于是后面每个 subagent 开局就知道需求文件在哪。自己另拼一个路径的话,
            #    确认书写进一处、注入的索引扫的是另一处,而且不报错。
            clarify_step(ch, brief_path=wb.notes / "需求.md", prompt=ASK),
            Step("干活", spec=coord,
                 prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
        ],
    )
