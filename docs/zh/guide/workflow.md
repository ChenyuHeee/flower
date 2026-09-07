# 设计流程

框架只管机制:一步怎么跑、会话怎么接、失败怎么办、上下文怎么省。
**[流程](../reference/glossary.md#流程)是你写的** —— 框架不知道你在做什么项目、用什么语言,
也不该知道。这一页讲怎么设计一个流程,`Step` 和 `Workflow` 的完整字段表在
[Python API](../reference/api.md)。

## 解决什么问题

一次[长程](../reference/glossary.md#长程)运行不是一句 prompt 就能说完的事:先问清需求、
再调研、再实现、再复核,每一段有自己的角色、自己的上下文、自己的验收条件。
全写进一句提示词里,模型会自己决定跳过哪一段;写成流程,**顺序、退出条件和状态传递就变成了
Python 代码** —— 可读、可测、可以只重跑坏掉的那一步。

`Workflow` 只做三件事:

- 按顺序跑一串[步骤](../reference/glossary.md#步骤)
- 决定每一步看得见前面的什么(三种会话接法 + 一个 `ctx` 字典)
- 决定什么时候重试、什么时候提前退出

它不含任何领域假设。切在哪、每步验收什么、不过怎么办 —— 这四件事就是"设计流程"。

## 怎么用(最小代码)

```python
# flows.py
from flower import AgentSpec, Step, Workflow

terse = AgentSpec(
    name="terse",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


def main() -> Workflow:
    return Workflow([
        # 新会话:只吃 prompt 里传进去的东西
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # 还是新会话,把上一步的产出注入 prompt(便宜、防污染)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
    ])
```

```bash
flower run flows.py:main -w /path/to/repo
```

`flower run` 的参数是 `模块:属性` 或 `文件路径:属性`。取到的对象可调用就先调一次,
拿到 `Workflow` 再跑;跑完终端上会打出总花费和运行清单的路径。

自己写驱动程序也行,`Workflow.run` 的第一个参数是 `Runtime`:

```python
ctx = await wf.run(rt, on_step=lambda step, r: print(f"{step.name} ok={r.ok} ${r.cost_usd:.4f}"))
```

## 它实际做了什么

### 一个 Step 收到什么、必须返回什么

`Step` 不是函数,是**声明**。真正执行的是 `Runtime.run(step.spec, 渲染出来的 prompt, ...)` ——
**一步 = 一次 `Runtime.run` = 一条[会话](../reference/glossary.md#会话)**。

前三个字段是位置参数,`Step(name, spec, prompt)`:

- `name` —— 步骤名。它同时是 `ctx` 里的键名、`runs/manifest.json` 里的行名、
  跨进程[血缘](../reference/glossary.md#血缘)的键。
- `spec` —— 用哪个 `AgentSpec` 跑。它决定这一步的工具白名单、模型和预算。
- `prompt` —— `str`,或者 `(ctx) -> str`。可调用时拿到当前 `ctx`,
  **这是把上一步产出喂进来最便宜的方式**(另一种是接会话,见下)。

这一步"返回"的是一个 `StepResult`,但在流程里你拿到的是两样东西:

- `ctx[step.name]` —— 默认是 `result.text`,给了 `reduce` 就换成 `reduce` 的返回值;
- `ctx["_results"][step.name]` —— 完整的 `StepResult`(花费、轮数、尝试次数、`session_id`)。

`result.text` **只收主线程的正文**:subagent 的发言在它自己的 transcript 里,派给它的
[任务书](../reference/glossary.md#任务书)是 `kind="prompt"`,断线的合成错误是 `kind="error"`
—— 三者都不进。

### reduce:不是糖

默认往下传的是模型说的原话。有些步骤的原话**不该**原样往下传:

```python
Step("确认需求", spec=确认者, prompt="帮我做一个 X",
     reduce=lambda r, ctx: ctx["_brief"].prompt_block())
```

实测确认需求那一步会在四段之外**贴进整份代码**。往下游传的必须是解析后的四段,
否则那堆代码会进下一步的 prompt。`clarify_step` 就是靠这个字段兜住的。

`reduce` **必须是同步函数**;`gate` / `when` / `on_reject` 可以是 async。

### 状态怎么在 ctx 里流动

`ctx` 是一个 `dict[str, Any]`,就是 `Workflow.context` 本身。每一步跑完按这张表写:

| 情况 | `ctx[步骤名]` | 别的 |
|---|---|---|
| `when(ctx)` 返回 False | **不写**,整步跳过 | 不产生 result,也不进 `_results` |
| 通过 | `reduce(result, ctx)`,没给就是 `result.text` | |
| 失败 + `on_fail="stop"`(默认) | **不写** | 写 `ctx["_failed_at"]`,整个流程停在这一步 |
| 失败 + `on_fail="skip"` | **不写** | 继续往下跑 |
| 失败 + `on_fail="continue"` | `result.text`(残缺的,**不过 `reduce`**) | 继续往下跑 |

不管通过与否,`ctx["_results"][步骤名]` 都会写;`result.session_id` 非空的话还会写进
`ctx["_sessions"]` 并记进血缘。

**判断这次流程成没成功,看 `ctx.get("_failed_at")`**,不是看最后一步有没有输出。

下划线开头的键都是 `Workflow.run` 自己放的:`_runtime`、`_on_event`、`_sessions`、`_results`、
`_lineage`、`_woke`、`_aborted`、`_failed_at`,别拿它们当自己的步骤名。各机制还会放自己的
(`_brief` / `_goal` / `_verdict` 等),完整清单见 [Python API](../reference/api.md)。

其中 `_runtime` 和 `_on_event` 是给 `gate` 用的:一个 gate 可以自己派一个 agent 去做判定,
而判定过程照样打到 UI 上 —— 不然那十几秒界面全黑,看起来像卡住。
[目标看守](goal.md)就是这么实现的。

`ctx` 是同一个 dict:**同一个 `Workflow` 对象跑第二次,上一次的键还在**。
要干净重来就新建一个,或者显式传 `context={}`。

!!! warning "on_fail 选 skip 时不写 `ctx[步骤名]`"
    下游写 `lambda ctx: ctx["某步"]` 会直接 `KeyError`。要带着残缺结果往下走,用
    `on_fail="continue"`;真要跳过,下游得自己 `ctx.get(...)` 兜底。

### 判定与打回:gate、on_reject、StepAbort

`gate(result, ctx) -> bool` 判的是"跑完了,但合格吗"。两个必须知道的细节:

- **`result.ok` 为假时 `gate` 根本不会被调用**(短路)。
- **每次尝试只调一次**,结论留着后面用 —— 它可能有副作用。`clarify_step` 的 gate 会把
  [需求确认书](../reference/glossary.md#需求确认书)落盘,重复触发就重复写盘。

gate 不过之后怎么重来,取决于给没给 `on_reject`:

| | 下一轮怎么跑 | manifest 里的名字 |
|---|---|---|
| 只有 `retries` | 重头跑,原 prompt、原 `resume_from` | `X#retry1` |
| 加上 `on_reject` | **续跑刚被否掉的那个会话**,prompt 换成 `on_reject` 的返回值,`fork` 强制 False | `X#round2` |

第二种是"打回去、带上差在哪、让它接着补" —— 已经干完的活和上下文都还在。
`on_reject` 返回空字符串,或者那次尝试根本没拿到 `session_id`,都会退化成重头跑。

`gate` 还可以抛 `StepAbort`,意思是**再试也没用,别消耗剩下的轮数**:

```python
from flower import StepAbort

def gate(result, ctx):
    if "这个环境装不了依赖" in result.text:
        raise StepAbort("环境缺依赖,再跑几轮也一样")
    return "验收通过" in result.text
```

抛出之后:原因记进 `ctx["_aborted"]`,这一步按失败处理并走 `on_fail`(默认 `"stop"`),
**重试循环当场 break**,剩下的 `retries` 一次都不消耗。

区别记牢:**返回 False 是"这次不行,再来一轮";`StepAbort` 是"再来也没用"。**
典型场合是目标被判为这个环境做不到、而且没人可问 —— 继续空转是最贵的选择。

### 两层重试别混

| | `Step.retries` | `Runtime(resilience=...)` |
|---|---|---|
| 管什么 | 业务失败:`gate` 不过、`result.ok` 为假 | 基础设施:网络抖动、断网、5xx |
| 怎么重来 | **整步重来**,同一个 prompt 和 `resume_from` | **从中断处 resume 续跑**,之前的花费不白费 |
| 之前做什么 | 什么都不做 | DNS + TCP 探针挂着等网络回来(不发 HTTP、不带凭证,探针必须免费) |
| 不可重试的 | —— | 凭证错、参数错立刻停,不死等 |

续跑用的那句 prompt **有意不含任何错误细节** —— 模型需要知道"被打断了、接着做",
不需要知道是 ENOTFOUND 还是 503。

### 把步骤串起来

步与步之间传递状态有三种接法,选哪种决定了下一步能看见什么:

| 写法 | 下一步看得见 | 用在哪 |
|---|---|---|
| `resume_from=None`(默认)+ prompt 里注入 | 只有你注入的那些字 | 各步独立。便宜、防污染 |
| `resume_from="上一步名"` | 完整会话历史 | 需要连贯记忆 |
| `resume_from="上一步名"` + `fork=True` | 完整历史,但另开一条分支 | 复核 / 多方案并行 / 重试不脏原线 |

`resume_from` 指向的那一步**必须真的产生过 session**。它被 `when` 跳过了、或者根本没跑,
`Workflow.run` 直接抛 `ValueError` —— 不静默降级成新会话,因为那会让"连贯记忆"这个假设
悄悄失效。

几条反复吃过亏的设计经验:

1. **一步一个可验收的目标。** 步骤边界就是上下文边界:`resume_from=None` 的地方,
   前面那些工具结果就彻底不再常驻。见[上下文经济学](context.md)。
2. **不确定就先 `clarify_step`。** 长程里"目标理解错了"是最贵的错误,
   而它恰恰是省上下文的那几层清不掉的那一类。见[前置确认](clarify.md)。
3. **派活的任务要自足。** subagent 是干净上下文,它不知道[协调者](../reference/glossary.md#协调者)
   知道的事。需要的背景写进任务书,或者告诉它去读哪个 artifact。
4. **长产出走磁盘,不走回话。** 这条已经写进 `WORKER_RULES` 了,你的 `instructions` 别把它
   抵消掉("把完整日志贴回来给我看")。
5. **`gate` 优先卡硬条件。** 文件在不在、退出码是不是 0,这种一行 Python 能判的别派模型。
   要模型来判就用现成的 `with_goal` —— 它把 gate 换成一个跑独立
   [判定者](../reference/glossary.md#判定者)的实现,别自己在 gate 里手搓一套。
6. **并行改同一个仓库就 `worker(isolate=True)`。** 收尾(合并、清理 worktree、开 PR)目前留给
   你的流程自己做,harness 只保证改动落在各自的 worktree 里。

### 工作台要挂在 Workflow 上

凡是流程要往[工作台](../reference/glossary.md#工作台)里写文件的场合 —— 典型是
`clarify_step(brief_path=...)` —— 必须自己建一个 `Workbench`,**同时**挂到 `Workflow.workbench`
和交给 `Runtime`:

```python
from pathlib import Path

from flower import (HumanChannel, Runtime, Step, Workbench, Workflow,
                    clarify_step, coordinator, worker)

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md", timeout_s=1800.0)

主控 = coordinator("协调者", "", {
    "coder": worker("写代码与测试。要动手实现的活派给它。",
                    "你负责实现。每改一处就跑一次验证,别攒到最后。"),
}, channel=ch)

wf = Workflow(
    [
        clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
        Step("干活", spec=主控, prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
    ],
    channel=ch,
    workbench=wb,
)

rt = Runtime(workspace=Path.cwd(), run_dir="runs", workbench=wb)
```

`channel` 挂在 workflow 上有两个理由:`run()` 会把它的 `on_event` 接到同一个事件出口
(仅当 `channel.on_event` 还是 `None`),驱动程序也靠这个字段知道该向谁回答。

!!! warning "自己拼工作台路径会静默失效"
    `Runtime(workbench=True)` 的默认位置是 `<run_dir>/workbench`,而 `Workbench(ws)` 默认是
    `<ws>/.flower` —— **两个不是同一个目录**。流程被 CLI 调用时看不到 `run_dir`,自己拼路径
    只会拼到别处,于是确认书写进 A 目录、注入的索引扫的是 B 目录,**并且不报错**。
    建好一个对象两边共用就没有这个问题;`Workflow.workbench` 存在时命令行的 `-W` 会被忽略,
    以它为准。

### `continuous=True`:同一个路径再跑一次

上面三种接法说的是**一次运行内**步与步之间。跨进程是另一个轴:

```python
Workflow([...], continuous=True)     # 默认值
```

同一个工作区再跑一次,每一步接着上次那条会话说 —— 靠 `<run_dir>/lineage.json` 里的
「步骤名 → session_id」。装载时每条记录都要过一遍 `runtime.has_session()` 验证 session 还在库里,
活着才用:血缘文件可能比 `sessions.db` 活得久,resume 一个不存在的 session 要等子进程起来才炸。

三条后果:

- **`resume_from=None` 不等于"全新会话"。** 第一次跑是,第二次跑不是。要每次都是新会话,
  显式写 `Workflow(..., continuous=False)`。
- **[接续](../reference/glossary.md#接续)时上下文会一直涨。** 接续时想说别的话就给
  `Step.resume_prompt` —— 对方上下文里已经有的东西不该重发。
- 显式写了 `resume_from` 的步骤不受影响,它优先。

!!! warning "步骤名是跨进程的键"
    改一个步骤名就等于断了那一步的血缘:下次跑不再接续,而且**不报错**。带 `#retry1` /
    `#round2` 后缀的重试名**不进血缘**(记的永远是原名),这也是"判定者永远是新会话"的实现
    方式之一。

完整设计和 `--new` 见[接续](continuity.md)。

## 什么时候不该用它

- **只跑一个 agent、也不需要判定** —— 别套 `Workflow`。直接 `await rt.run(spec, "…")`,
  或者命令行 `flower once "读一眼这个仓库"`。
- **形状就是"问清需求 → 定目标 → 干活"** —— 用现成的
  [`starter_flow()`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py),
  不用自己写:

    ```python
    from flower import starter_flow

    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs",
                      rounds=3, timeout_s=1800.0, isolate=False)
    ```

    它是**三步**:`确认需求` → `设定目标` → `干活`(带判定循环,判定步骤叫 `干活·判定#N`)。
    `goal=False` 时没有第二步和判定循环,`clarify_only=True` 时只留第一步。
    它自带 `HumanChannel` 和 `Workbench` 并挂在 workflow 上,所以
    `Runtime(workbench=wf.workbench)` 直接拿来用,别另拼一个。

    不写代码也行,进项目目录 `flower "帮我做一个 X"` 跑的就是它。
    **它不是"推荐的流程设计"**,只是让你零配置就能跑起来。

- **步骤切得比"一个可验收的目标"还细** —— 净亏。每一步都要起一条新会话,
  而一条新会话有启动地板(协调者实测约 34k 上下文),摊不薄。
- **想事后回滚到某条消息** —— `Workflow` 这条路走不通,它从不传 `resume_at`。
  直接调 `Runtime.run(spec, "从这里重来", resume=sid, resume_at=uuid)`。

角色怎么选(`coordinator` / `worker` / `clarify` / `judge` / `oracle`)、`Step` 与 `Workflow` 的
逐字段语义,见 [Python API](../reference/api.md);名词见[术语表](../reference/glossary.md)。
