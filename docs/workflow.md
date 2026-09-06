# 设计一个 workflow

> 框架管**机制**:一步怎么跑、会话怎么接、失败怎么办、上下文怎么省。
> **流程是你的活** —— 框架不知道你在做什么项目、用什么语言,也不该知道。

```python
# flows.py
from flower import Step, Workflow

def main():
    return Workflow([
        Step("调研", spec=researcher, prompt="梳理 X 模块的现状与约束"),
        Step("方案", spec=researcher, prompt=lambda c: f"基于以下调研给出方案:\n{c['调研']}"),
        Step("实现", spec=coder,      prompt="按上面的方案实现", resume_from="方案"),
        Step("复核", spec=coder,      prompt="以审查者视角找问题", resume_from="实现",
             fork=True, retries=1, gate=lambda r, c: "阻断" not in r.text),
    ])
```

```bash
.venv/bin/python -m flower.cli -w /path/to/repo -W run flows.py:main
```

---

## `Step`

| 字段 | 类型 | 默认 | 作用 |
|---|---|---|---|
| `name` | `str` | — | 步骤名。**也是 `ctx` 里的键名**,下游用它取结果 |
| `spec` | `AgentSpec` | — | 用哪个角色跑 |
| `prompt` | `str \| Callable[[Ctx], str]` | — | 给它什么任务。可调用的话,拿到当前 `ctx` |
| `resume_from` | `str \| None` | `None` | 接哪一步的会话。见「三种接法」 |
| `fork` | `bool` | `False` | 接的时候分叉,不污染原会话 |
| `retries` | `int` | `0` | 失败或 `gate` 不过时整步重试几次 |
| `gate` | `(StepResult, Ctx) -> bool` | `None` | 返回 `False` 视为失败。**每次尝试只调一次** |
| `when` | `(Ctx) -> bool` | `None` | 返回 `False` 则整步跳过 |
| `reduce` | `(StepResult, Ctx) -> str` | `None` | 决定 `ctx[name]` 里放什么。默认放 `result.text` |
| `on_fail` | `"stop"｜"skip"｜"continue"` | `"stop"` | 最终失败后往哪走 |

### 三种会话接法

| 写法 | 下一步看得见什么 | 用在哪 |
|---|---|---|
| `resume_from=None` | 只有 prompt 里传进去的 | 各步独立。便宜,防污染 |
| `resume_from="上一步"` | 完整会话历史 | 需要连贯记忆 |
| `resume_from="上一步", fork=True` | 完整历史,但另开一条分支 | 复核 / 多方案并行 / 重试不脏原线 |

`resume_from` 指向的那一步**必须真的产生过 session**。它被 `when` 跳过了、
或者根本没跑,`Workflow.run` 直接抛 `ValueError` —— 不静默降级成新会话,
因为那会让"连贯记忆"这个假设悄悄失效。

### 执行顺序(精确)

每一步:

```
when(ctx) 返 False ─────────────────────────────► 跳过,不写 ctx[name]
    │
    ▼
解析 resume_from ──── 那一步没产生 session ─────► ValueError
    │
    ▼
┌─ 重试循环 (retries + 1 次) ────────────────────┐
│   runtime.run(spec, prompt(ctx), resume, fork) │
│   passed = result.ok 且 gate(result, ctx)      │  ← gate 每次尝试只调一次
│   passed 就跳出                                 │
└────────────────────────────────────────────────┘
    │
    ▼
记 ctx["_results"][name](最后一次尝试)、调 on_step、记 session_id(失败也记)
    │
    ├─ passed ──► ctx[name] = reduce(result, ctx) 或 result.text ──► 下一步
    │
    └─ 失败 ──┬─ on_fail="stop"     ► ctx["_failed_at"] = name,整个 workflow 停
              ├─ on_fail="skip"     ► 继续,**不写 ctx[name]**(下游取它会 KeyError)
              └─ on_fail="continue" ► ctx[name] = result.text(**不过 reduce**),带着残缺往下走
```

几个容易被忽略的细节:

- **`result.ok` 为假时 `gate` 根本不会被调用**(短路)。gate 只用来判"跑完了但不合格"。
- **`gate` 可能有副作用**,所以每次尝试只调一次并复用结论 —— `clarify_step` 的 gate
  会把确认书落盘,重复触发就重复写盘。改这个循环时留意这一点。
- 重试的那几次在 `manifest.json` 里叫 `name#retry1`、`name#retry2`,便于事后区分。
- **重试用的还是同一个 `resume`**,不是接着上一次失败的会话 —— 整步重来。
  (接着失败处续跑是 `Runtime` 内部处理断网时干的事,见「两层重试」。)

### `reduce`:不是糖

默认 `ctx[step.name] = result.text` —— 模型说的原话。有些步骤的原话**不该**原样往下传:

```python
Step("确认需求", ..., reduce=lambda r, ctx: ctx["_brief"].prompt_block())
```

实测过确认需求那一步会在四段之外**贴进整份代码**。往下游传的必须是解析后的四段,
否则那堆代码会进下一步的 prompt。`clarify_step` 就是靠这个字段兜住的。

## 判定与打回

`gate` 返回 False 时,默认是**重头再跑一次**(同样的 prompt、同样的 `resume_from`)。
给了 `Step.on_reject`,语义就变成**接着做**:

| | 下一轮怎么跑 | 步骤名 |
|---|---|---|
| 只有 `retries` | 重头跑,原 prompt | `X#retry1` |
| 加上 `on_reject` | **续跑刚被否掉的那个 session**,prompt 换成 `on_reject` 的返回值 | `X#round2` |

第二种是"打回去、带上差在哪、让它接着补"—— 已经干完的活和上下文都还在。
目标未达成时要的是这个,见 [goal.md](goal.md)。

`gate` / `when` / `on_reject` **都可以是 async**。这是为了让它们能派 agent:
`Workflow.run` 把运行时和事件出口放进 `ctx["_runtime"]` / `ctx["_on_event"]`,
于是一个 gate 可以自己起一个 agent 来做判定,而判定过程照样打到 UI 上
(不然那十几秒界面全黑,看起来就像卡住)。

`gate` 还可以抛 `StepAbort`:意思是**再试也没用,别消耗剩下的轮数**。
本步按失败处理并走 `on_fail`,原因记在 `ctx["_aborted"]`。
典型场合:目标被判为做不到、而且没人可问。

---

## 已经有一个起步流程

在自己设计之前,`flower "帮我做一个 X"` 直接可跑 —— 背后是
[`flower/workflow/starter.py`](../flower/workflow/starter.py) 里的 `starter_flow()`:
确认需求 → 派人干活,两步,不含任何领域假设。它也可以当库用:

```python
from flower import starter_flow
wf = starter_flow("帮我做一个 X", workspace=".", clarify_only=False,
                  max_asks=6, timeout_s=1800, isolate=False)
```

**它不是"推荐的 workflow 设计"**,只是让你零配置就能跑起来。
它现在是三步:确认需求 → 设定目标 → 干活(带判定循环)。领域流程是你的活:
照下面的 `Step`/`Workflow` 写自己的,用 `flower run flows.py:main` 跑。
`examples/trial.py` 是照着抄的模板。

---

## `Workflow`

```python
Workflow(steps, name="workflow", context={}, channel=None, workbench=None)
```

| 字段 | 作用 |
|---|---|
| `steps` | `list[Step]`,按顺序跑 |
| `name` | 标识用 |
| `context` | 初始 `ctx`。可以预塞东西进去给第一步的 `prompt` 用 |
| `channel` | `HumanChannel` —— 需要停下来问人时挂这里 |
| `workbench` | `Workbench` —— 由 workflow 指定的工作台。`None` = 沿用驱动自己的选择(`-W`) |

```python
ctx = await wf.run(runtime, on_event=..., on_step=...)
```

### 后两个字段是给驱动程序看的

`channel` 挂在 workflow 上而不是让 UI 自己去找,是为了两件事:
`run()` 会把它的 `on_event` 接到同一个事件出口(UI 只需要认 `Event("ask")`,
不必额外接线);驱动程序(`cli.py`)也能找到它,从而知道该向谁回答。

`workbench` 是同一个道理:`cli.py` 发现它以后,会把它交给 `Runtime`,
而不是自己按 `-W` 造一个。**凡是 workflow 要往工作台里写文件的场合,这个字段是必须的**
—— 典型是 `clarify_step(brief_path=...)`。工作台索引进的是每个 agent 的 system prompt,
确认书必须落在**真正被注入的那个**工作台里,后面每一个 subagent 开局才知道需求文件在哪。

而 `Runtime(workbench=True)` 的默认位置是 `<run_dir>/workbench`,`main()` 被 CLI 调用时
看不到 `run_dir` —— 自己拼路径只会拼到别处,于是**确认书写进 A 目录、注入的索引扫 B 目录,
并且不报错**。建好再挂上去,两边就是同一个对象:

```python
wb = Workbench(Path.cwd()).ensure()
return Workflow(channel=ch, workbench=wb, steps=[
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="…"),
    ...,
])
```

自己写驱动时同理:同一个 `Workbench` 对象同时给 `Workflow` 和 `Runtime`。

### `ctx` 里有什么

| 键 | 内容 |
|---|---|
| `ctx["步骤名"]` | 那一步的产出(`str`)。跳过的步骤没有这个键 |
| `ctx["_sessions"]` | `步骤名 → session_id` |
| `ctx["_results"]` | `步骤名 → StepResult`(要花费、轮数、重试次数看这里) |
| `ctx["_failed_at"]` | 有值 = 中途停了。**判断成功与否看这个** |
| `ctx["_brief"]` / `ctx["_brief_missing"]` | `clarify_step` 放的,见 [clarify.md](clarify.md) |

`ctx` 就是 `Workflow.context` 本身。同一个 `Workflow` 对象跑第二次,上一次的键还在 ——
要干净重来就新建一个,或者显式传 `context={}`。

## 角色

一步用哪个 `AgentSpec`,决定了它的工具白名单、上下文形状和花钱方式。
三个现成的造法,覆盖绝大多数场景:

```python
from flower import clarify, coordinator, worker

# 干活的 subagent 定义(不是 AgentSpec,是给协调者派的名册项)
改代码 = worker("修 bug 并提交。要动手改代码的活派给它。",
                "改代码、跑验证、commit。", isolate=True)
调研   = worker("只读地看代码,不改任何东西。",
                "你只读。", tools=["Read", "Grep", "Glob"])

# 只协调不动手的主 agent
主控 = coordinator("主控", "目标:把 X 做出来。", {"改代码": 改代码, "调研": 调研})

# 只提问不动手的确认者(见 clarify.md)
确认 = clarify("确认需求", channel)
```

| | `coordinator()` | `worker()` | `clarify()` |
|---|---|---|---|
| 返回 | `AgentSpec` | `AgentDefinition` | `AgentSpec` |
| 默认工具 | `Agent` `TodoWrite` `Read` + 受限 `Bash` | `Read` `Write` `Edit` `Bash` `Glob` `Grep` | `ask` + `Read` `Glob` `Grep` |
| 默认模型 | 继承环境 | `"inherit"` —— 干活的不该降级 | 继承环境 |
| 附带纪律提示词 | `COORDINATOR_RULES` | `WORKER_RULES`(`discipline=False` 可关) | `CLARIFIER_RULES` |

`worker(isolate=True)` 让这个角色每次被派活都自动拿到独立的 git worktree ——
并行改同一个仓库时必开,否则多个 subagent 在同一个 checkout 上互相 `git checkout`,
分支会串。**由 hook 强制执行,提示词里一个字都不提**(不需要隔离的角色一个 token
都不会被加上)。要求 workspace 是 git 仓库。

要更细的控制就直接写 `AgentSpec`:

```python
AgentSpec(
    name="coder",
    instructions="按方案实现。每改一处就跑一次测试。",   # 追加在原生提示词之后
    allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    permission_mode="acceptEdits",
    max_budget_usd=5.0,          # 硬熔断
    max_turns=40,
    model=None, effort=None,     # None = 跟环境
    agents={...},                # 它自己的 subagent 名册
    workbench=True,              # 是否注入工作台索引
)
```

> **不要用 `disallowed_tools` 限制主 agent。** 它是**会话级**的,会把 subagent 的
> Bash/Write 一起禁掉(实测报错原文:"Bash is disabled for this session, in subagents
> as well as here")。正确做法是 `allowed_tools` 不给,再用 PreToolUse hook 按
> `agent_id` 只拦主线程 —— `coordinator()` 已经这么做了。

## `Runtime`

```python
Runtime(
    workspace="/path/to/repo",   # agent 的 cwd
    run_dir="runs",              # sessions.db + manifest.json + 工作台
    workbench=False,             # True = 开工作台(脚本/产出/笔记 + 索引注入)
    trim=False,                  # True = resume 时把旧的大工具结果换成文件指针
    ephemeral=True,              # 过期剪枝:git status 这类结果几轮后标记为过期
    keep_denials=1,              # 被拒的工具调用留最近几次,其余摘掉
    spill_threshold=4000,        # 超过这么多字符的工具结果落盘,上下文里换成路径
    resilience=True,             # 断网探针 + 重试 + resume 续跑
    portable=True,               # 不读宿主机 ~/.claude/ 与项目 .claude/
)
```

跑一次 = 一个 session:

```python
result = await rt.run(spec, "任务", step_name="调研",
                      resume=None, fork=False, resume_at=None, on_event=None)
```

`StepResult`:`text` / `session_id` / `ok` / `cost_usd` / `num_turns` / `error` /
`attempts` / `errors` / `resumed` / `duration_s`。后四个只进 `manifest.json`,
**模型看不到** —— 排查故障看那里。

`result.text` 只收**主线程**的正文:subagent 的发言在它自己的 transcript 里,
派给它的任务书是 `kind="prompt"`,断线的合成错误是 `kind="error"` —— 三者都不进。

### 两层重试

容易混,分清楚:

| | `Step.retries` | `Runtime(resilience=...)` |
|---|---|---|
| 管什么 | 业务失败:`gate` 不过、`result.ok` 为假 | 基础设施:网络抖动、断网、5xx |
| 怎么重来 | **整步重来**,同一个 prompt 和 resume | **从中断处 resume 续跑**,之前的花费不白费 |
| 之前 | 什么都不做 | DNS+TCP 探针挂着等网络回来(不发 HTTP、不带凭证 —— 探针必须免费) |
| 不可重试的 | — | 凭证错、参数错立刻停,不死等 |

重试的 prompt **有意不含任何错误细节** —— 模型需要知道"被打断了、接着做",
不需要知道是 ENOTFOUND 还是 503。

## 事后再来一次

每一步的 `session_id` 都写进 `runs/manifest.json`,所以**任意一步事后都能续跑、
分叉或回滚**:

```python
rt = Runtime(workspace="/path/to/repo", run_dir="runs")

await rt.run(spec, "接着上次那步继续", resume=sid)                 # 续跑
await rt.run(spec, "换个方案试试",     resume=sid, fork=True)      # 分叉,原线不动
await rt.run(spec, "从这里重来",       resume=sid, resume_at=uuid) # 回滚到某条消息
```

查库:

```python
await rt.store.list_sessions(rt.project_key)          # [{session_id, mtime}, ...]
await rt.store.load({"project_key": rt.project_key, "session_id": sid})
await rt.store.list_subkeys({...})                    # 每个 subagent 的独立 transcript
```

`project_key` 由 SDK 从 **cwd** 推导(`/`、`_`、`.` 都换成 `-`),调用方指定不了 ——
查库必须用 `rt.project_key`,不是自定义标签。

## 设计建议

从上下文经济学出发,这几条是反复吃过亏的:

1. **一步一个可验收的目标。** 步骤边界就是上下文边界:`resume_from=None` 的地方,
   前面那些工具结果就彻底不再常驻。
2. **不确定就先 `clarify_step`。** 长程里"目标理解错了"是最贵的错误,
   而它恰恰是剪枝清不掉的那一类。见 [clarify.md](clarify.md)。
3. **派活的任务要自足。** subagent 是干净上下文,它不知道协调者知道的事。
   需要的背景写进任务书,或者告诉它去读哪个 artifact。
4. **长产出走磁盘,不走回话。** 这条已经写进 `WORKER_RULES` 了,
   你的 `instructions` 别把它抵消掉("把完整日志贴回来给我看")。
5. **`gate` 用来卡硬条件,不用来做判断。** 它是纯 Python,别在里面调模型 ——
   要模型判断就再加一个 `Step`。
6. **并行改同一个仓库就 `isolate=True`。** 收尾(合并、清理 worktree、开 PR)
   目前留给你的 workflow 自己做,harness 只保证改动落在各自的 worktree 里。
