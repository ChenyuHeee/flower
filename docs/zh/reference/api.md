# Python API

这一页穷尽 `flower` 顶层 `__all__` 的 **62 个公开符号**:签名、参数、默认值、语义、
公开属性和方法。读完不必再打开源码找参数。

组织方式按**关心的事情**分,不按模块文件分 —— 想知道"怎么拦住[协调者](glossary.md#协调者)
自己动手",去 [hook 层](#hook);想知道"上一步的结果怎么传给下一步",去[流程](#流程)。
术语一律按[术语表](glossary.md)。

版本 `0.1.0`,依赖 `claude-agent-sdk>=0.2.152`。所有签名逐字对应源码。

```python
from flower import Runtime, Workflow, Step, coordinator, worker   # 顶层一次导入
```

## 这页有什么 {#索引}

| 关心的事 | 符号 |
|---|---|
| [跑一个 agent](#运行时) | `Runtime` `StepResult` |
| [把多步串起来](#流程) | `Step` `Workflow` `StepAbort` `clarify_step` `goal_step` `with_goal` `starter_flow` `wake_state` `BRIEF_KEY` `MISSING_KEY` `CLARIFY_RESUME` `GOAL_KEY` `VERDICT_KEY` `ROUND_KEY` |
| [造一个角色](#角色工厂) | `coordinator` `worker` `clarify` `judge` `oracle` `COORDINATOR_RULES` `WORKER_RULES` `CLARIFIER_RULES` `JUDGE_RULES` `ORACLE_RULES` |
| [手写 agent 定义](#agent-定义) | `AgentSpec` `build_options` `CompactPolicy` `HandoffPolicy` `default_window` |
| [结构化文书](#文书) | `Brief` `Handoff` `Goal` `Verdict` |
| [拦工具、剪结果、分隔离](#hook) | `whitelist_guard` `delegate_guard` `spill_guard` `index_guard` `isolate_guard` `isolated` `wants_isolation` `workbench_hooks` `merge_hooks` |
| [落盘的工作目录](#工作台) | `Workbench` |
| [会话怎么存、存什么](#会话存储) | `SqliteSessionStore` `TrimmingSessionStore` `PruningSessionStore` `TrimPolicy` `EphemeralPolicy` `PrunePolicy` `is_ephemeral` `trim_report` |
| [断网了怎么办](#韧性) | `Resilience` `classify` `endpoint` `reachable` |
| [换掉 UI](#事件与交互) | `Event` `normalize` `Ask` `HumanChannel` |
| [跨进程接上次](#血缘) | `Lineage` |

## 六个会咬人的默认值 {#危险默认值}

这六条不是边角料,是最常见的六次翻车。每条在对应小节里有完整说明。

| 默认值 | 后果 | 详见 |
|---|---|---|
| `Runtime(workbench=False)` + `coordinator()` | 主线程的 `Bash`/`Write`/`Edit` **一道 hook 都没有** | [Runtime](#runtime) |
| `Runtime(handoff=True)` | 强制给 spec 装 `CompactPolicy(mode="no_summary")`,即 `DISABLE_AUTO_COMPACT=1` | [Runtime](#runtime) |
| `Workflow(continuous=True)` | `resume_from=None` 的步骤仍会跨进程接上次那条会话 | [Workflow](#workflow) |
| `build_options(fork=True)` 不给 `resume` | 静默失效,不报错 | [build_options](#build-options) |
| `clarify(max_turns=<小数字>)` | 把"提问不限次数"变成空话 —— 每次提问就是一轮 | [clarify()](#clarify-role) |
| `AgentSpec.disallowed_tools` | 会话级,连 subagent 一起禁掉 | [AgentSpec](#agentspec) |

---

## 运行时 {#运行时}

源码:[`flower/core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)

`Runtime` 是执行核心。它持有工作区、[会话存储](glossary.md#会话存储)、[工作台](glossary.md#工作台)、
[韧性](glossary.md#韧性)策略和[换代](glossary.md#换代)策略,对外只有一个动词:`run` 一步。
重试、被打断后续跑、上下文满了换代,全在这一个调用里面完成。

### `Runtime` {#runtime}

```python
Runtime(
    *,
    workspace: str | Path,
    run_dir: str | Path = "runs",
    portable: bool = True,
    trim: TrimPolicy | bool = False,
    ephemeral: EphemeralPolicy | bool = True,
    keep_denials: int = 1,
    workbench: Workbench | bool = False,
    spill_threshold: int | None = 4000,
    resilience: Resilience | bool = True,
    handoff: HandoffPolicy | bool = True,
)
```

构造参数**全部是 keyword-only**(`*` 在最前),`workspace` 必填。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `workspace` | `str \| Path` | 必填 | agent 的 `cwd`。构造时 resolve 并 `mkdir(parents=True, exist_ok=True)`。SDK 的 `project_key` 由它推导 —— 目录被拷走,旧 `session_id` 就查不到了 |
| `run_dir` | `str \| Path` | `"runs"` | 放 `sessions.db`、`manifest.json`、`lineage.json`,以及 `workbench=True` 时的默认工作台。同样 resolve 并 mkdir |
| `portable` | `bool` | `True` | 透传给 `build_options(portable=)`,即 `setting_sources=[]`:不读宿主机 `~/.claude/`,也不读项目 `.claude/`。见[可移植](glossary.md#可移植) |
| `trim` | `TrimPolicy \| bool` | `False` | 给实例就直接用;给 `bool` 则 `TrimPolicy(enabled=bool(trim))`。**关掉只是不裁剪大结果,剪除照做** |
| `ephemeral` | `EphemeralPolicy \| bool` | `True` | 同上转换规则。和 `coordinator(glance=True)` 是一对 —— 放行主线程跑 `git status`,就得保证那个结果会过期 |
| `keep_denials` | `int` | `1` | 传给 `PrunePolicy(keep_denials=)`。保留最近 N 次被拒的工具调用,更早的连调用带结果一起摘掉 |
| `workbench` | `Workbench \| bool` | `False` | 给实例就直接用;给 `True` 则建 `Workbench(workspace, home=run_dir / "workbench")`(**默认落在工作区外**)。随后立刻 `refresh()` |
| `spill_threshold` | `int \| None` | `4000` | 工具结果超过多少字符就[落盘](glossary.md#落盘)。`None` 或 `0` = 不装 `spill_guard` |
| `resilience` | `Resilience \| bool` | `True` | 同转换规则 |
| `handoff` | `HandoffPolicy \| bool` | `True` | 同转换规则 |

**会话存储是写死的**:永远是
`PruningSessionStore(run_dir/"sessions.db", workspace=..., policy=<TrimPolicy>, ephemeral=<EphemeralPolicy>, prune=PrunePolicy(keep_denials=...))`。
构造参数**不提供**换后端的入口 —— 要换,自己构造 `AgentSpec` + `build_options(session_store=...)`,
或者构造完覆盖 `rt.store`。

构造的最后两步是 `load_dotenv()` 和 `check_credentials()`,**后者有错就 `raise RuntimeError`**。
没凭证时是构造阶段就炸,不是等到 `run()`。

!!! warning "`workbench=False` + `coordinator()` = 主线程一道墙都没有"
    `delegate_guard` 只在 `workbench_hooks` 里装,而 `workbench_hooks` 只在 `self.workbench is not None`
    时才调;`whitelist_guard` 又被 `if not spec.delegate_only` 跳过。而 `coordinator()` 恒设
    `delegate_only=True`、默认 `glance=True` 给了 `Bash`。

    **结论:协调者配上 `Runtime(workbench=False)` 时,它的 `Bash`/`Write`/`Edit` 没有任何 hook 拦。**
    用 `coordinator()` 就把 `workbench` 打开 —— `Runtime(..., workbench=True)` 或传一个
    `Workbench` 实例。

!!! warning "`handoff=True`(默认)会强制关掉 auto-compact"
    `_attempt` 里:`handoff.enabled and spec.compact is None` → `spec = replace(spec, compact=CompactPolicy(mode="no_summary"))`,
    落到子进程就是 `DISABLE_AUTO_COMPACT=1`。理由是两套机制同时开着,上下文回落到底是谁干的说不清。

    **代价:写交接那一步必须有降级路径**(`handoff.degraded`),因为没有 compact 兜底了。
    要保留 auto-compact,就显式给 `AgentSpec.compact`(spec 自己给了就尊重它,不覆盖)。

#### 公开属性 {#runtime-属性}

| 属性 | 类型 | 说明 |
|---|---|---|
| `workspace` | `Path` | resolve 后的工作区 |
| `run_dir` | `Path` | resolve 后的运行目录 |
| `portable` | `bool` | 原样保存 |
| `store` | `PruningSessionStore` | 会话存储。想换后端只能构造后覆盖它 |
| `resilience` | `Resilience` | 规整后的实例 |
| `handoff` | `HandoffPolicy` | 规整后的实例 |
| `workbench` | `Workbench \| None` | `workbench=False` 时是 `None` |
| `spill_threshold` | `int \| None` | 原样保存,`_attempt` 里传给 `workbench_hooks` |
| `results` | `list[StepResult]` | 本进程跑过的每一步,按顺序追加 |
| `run_id` | `str` | `"%Y%m%d-%H%M%S" + "-" + uuid4().hex[:6]`。**必须每实例唯一** —— `manifest.json` 按 `run` 字段去重,两个 id 撞上时后写的会把对方的行当成自己上次写的删掉 |
| `on_session` | `Callable[[str], None] \| None` | 拿到新 `session_id` 时**立刻**回调,默认 `None`。**只该罩在 `runtime.run` 这一句上** —— [判定者](glossary.md#判定者)用同一个 `Runtime`,gate 期间还挂着会把判定者的会话写进干活那一步的[血缘](glossary.md#血缘) |

类常量:`INTERRUPTED = "interrupted-by-human"`、`HANDOFF_DUE = "context-full-handoff"`、
`INTERRUPT_NOTE`(打断续跑时附在人的话后面的一段,说明"当时在飞的工具调用返回 interrupted
是打断的正常副作用,不是环境故障")。

#### 公开方法 {#runtime-方法}

| 方法 | 签名 | 说明 |
|---|---|---|
| `run` | `async (spec, prompt, *, step_name=None, resume=None, fork=False, resume_at=None, on_event=None) -> StepResult` | 跑一步。见下 |
| `interrupt` | `(message: str = "") -> None` | 请求打断当前这一轮。**任何线程可调**。协作式:在**消息边界**干净断开,不硬取消。空串 = 只打断不说话 |
| `rescue` | `() -> None` | 被硬杀前尽量把账落全,由 `SIGHUP`/`SIGTERM` 处理器调。在飞的那一步也写进 manifest,`error="killed-by-signal"`。只做同步小写盘 |
| `manifest_path` | `@property -> Path` | `run_dir / "manifest.json"` |
| `project_key` | `@property -> str` | `str(workspace.resolve())` 里 `/`、`_`、`.` 全换成 `-`。**SDK 由 cwd 推导,调用方指定不了** |
| `has_session` | `(session_id: str) -> bool` | 这个 id 在**本工作区**下还查得到吗。同步,不读 payload |
| `context_of` | `(session_id: str) -> int` | 某条会话最后一轮的上下文规模,委托 `store.last_context` |
| `total_cost` | `() -> float` | `round(sum(r.cost_usd for r in self.results), 4)` |
| `close` | `() -> None` | `self.store.close()` |

#### `Runtime.run(...)` {#runtime-run}

```python
async def run(
    self,
    spec: AgentSpec,
    prompt: str,
    *,
    step_name: str | None = None,
    resume: str | None = None,
    fork: bool = False,
    resume_at: str | None = None,
    on_event: Callable[[Event], None] | None = None,
) -> StepResult
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `spec` | `AgentSpec` | 必填,位置参数 | 要跑的 agent 声明 |
| `prompt` | `str` | 必填,位置参数 | 这一轮说的话 |
| `step_name` | `str \| None` | `None` | 落在 `StepResult.step`、manifest、血缘里的键。`None` → `spec.name` |
| `resume` | `str \| None` | `None` | 续跑这条 `session_id` |
| `fork` | `bool` | `False` | 分叉出新会话,不污染原会话。**只在 `resume` 为真时生效** |
| `resume_at` | `str \| None` | `None` | 从某条消息处续跑(回滚)。同样**只在 `resume` 为真时生效** |
| `on_event` | `Callable[[Event], None] \| None` | `None` | 事件出口,见 [`Event`](#event) |

每步开头把上下文水位归零(`self._ctx, self._warned = 0, False`)。之后是一个循环,四条出口:

1. **成功** → 跳出。
2. **人打断**(`result.error == INTERRUPTED`)→ **不受 `max_attempts` 约束**,不等网络。
   带着人的话 `resume` 同一条会话,`attempt -= 1`(打断不算失败尝试),prompt = 人的话 + `INTERRUPT_NOTE`。
   **没拿到 `session_id` 就只能停下**。
3. **上下文满**(`result.error == HANDOFF_DUE`,或 `handoff.enabled` 且拿到了 `session_id` 且
   `is_overflow(...)` 命中)→ **也不受 `max_attempts` 约束**。先查 `len(result.retired) >= handoff.max_generations`,
   超了就把 error 换成一句诊断并跳出;否则写[交接书](glossary.md#交接书) → `resume=None, fork=False`
   (**全新会话**)→ prompt 换成 `h.prompt_block()` → 水位归零 → `attempt -= 1`。
4. **可重试故障** → `not resilience.enabled or attempt >= max_attempts` 就跳出;
   `classify(error)` 判定不该重试也跳出;否则发 `Event("retry")`、`wait_online()` 挂着等网络、
   `sleep(delay_for(attempt))`;**拿到过 `session_id` 就 `resume` 续跑**(prompt 换成
   `resilience.resume_prompt`),并把 `result.resumed` 置 `True`。

收尾:写 `ended_at`、追加进 `self.results`、写 `manifest.json`。

`manifest.json` 是**追加**语义:每次写都重读磁盘,按 `run` 字段去重(自己的行换新,别人的行留着),
所以同一个 `run_dir` 下并行跑两个 flower 是安全的 —— 前提是 `run_id` 不撞。

**换代的三个观测点**(都是 `Event("handoff")`,`payload["phase"]` 区分):
`near`(逼近 `warn_at`,每代只发一次)、`writing`(正在写交接,要十几秒)、
`done`(payload 带 `degraded` / `path` / `sections`)。写交接那一轮用
`replace(spec, max_budget_usd=None)` 跑 —— 交接必须写得出来,不能卡在预算上;
且 `on_event=None`,这一轮不往 UI 刷。

交接落盘在 `<workbench.notes>/交接-<步骤名>.md`;**没有工作台就不落盘**,文书照样通过 prompt
交给接手者,只是事后翻不到。旧交接被移到 `notes/archive/交接/<名>-<时间戳>.md`。

### `StepResult` {#stepresult}

```python
@dataclass
class StepResult:
    step: str
    session_id: str | None = None
    ok: bool = False
    cost_usd: float = 0.0
    num_turns: int = 0
    text: str = ""
    error: str | None = None
    started_at: float = 0.0
    ended_at: float = 0.0
    attempts: int = 1
    errors: list[str] = field(default_factory=list)
    resumed: bool = False
    retired: list[str] = field(default_factory=list)
    context: int = 0
```

一步跑完的全部账。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `step` | `str` | 必填 | 步骤名(`step_name` 或 `spec.name`) |
| `session_id` | `str \| None` | `None` | **永远是最后接班的那条会话** —— 中途换代烧掉的在 `retired` 里 |
| `ok` | `bool` | `False` | 这一步成没成 |
| `cost_usd` | `float` | `0.0` | 美元。重试与换代中是**累加**的 |
| `num_turns` | `int` | `0` | 轮数,同样累加 |
| `text` | `str` | `""` | **只含主线程的正文**。subagent 的发言留在它自己的 transcript,派给它的任务书是 `kind="prompt"`,两者都不进 |
| `error` | `str \| None` | `None` | 失败原因。特殊值见 `Runtime.INTERRUPTED` / `Runtime.HANDOFF_DUE` |
| `started_at` / `ended_at` | `float` | `0.0` | Unix 时间戳 |
| `attempts` | `int` | `1` | 实际尝试次数。打断和换代**不计入** |
| `errors` | `list[str]` | `[]` | 收拢的合成 API 错误消息,**不进 `text`** |
| `resumed` | `bool` | `False` | 中途是否 resume 续跑过 |
| `retired` | `list[str]` | `[]` | 这一步换代时烧掉的 `session_id`,按序 |
| `context` | `int` | `0` | 最后一轮主线程实际看到的上下文规模,即换代判据 |

| 属性 | 类型 | 说明 |
|---|---|---|
| `duration_s` | `@property -> float` | `round(ended_at - started_at, 2)`,没跑完是 `0.0` |

---

## 流程 {#流程}

源码:[`flower/workflow/`](https://github.com/ChenyuHeee/flower/tree/main/flower/workflow)

[流程](glossary.md#流程)是按顺序串起来的一组[步骤](glossary.md#步骤),外加步骤之间怎么传状态、
什么时候提前退出。**框架不提供现成流程,流程是你写的** —— `starter_flow` 只是一个能跑的样板。

类型别名 `Ctx = dict[str, Any]`(`flower.workflow.base.Ctx`,在 `flower.workflow.__all__` 里,
不在顶层 `__all__`)。

### `Step` {#step}

```python
@dataclass
class Step:
    name: str
    spec: AgentSpec
    prompt: str | Callable[[Ctx], str]

    resume_from: str | None = None
    fork: bool = False

    retries: int = 0
    gate: Callable[[StepResult, Ctx], bool] | None = None
    on_fail: str = "stop"
    when: Callable[[Ctx], bool] | None = None
    on_reject: Callable[[StepResult, Ctx], str] | None = None
    resume_prompt: str | Callable[[Ctx], str] | None = None
    reduce: Callable[[StepResult, Ctx], str] | None = None
```

一个步骤的**声明**。`Step` 本身不是函数 —— 真正执行的是 `Runtime.run(step.spec, prompt, ...)`。
前三个字段是位置参数,`Step("取词", terse, "读 seed.txt …")` 是合法写法。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `name` | `str` | 必填 | 步骤名。**跨进程稳定的键** —— 落在 `ctx[name]`、`ctx["_results"]`、manifest 和血缘里。改名 = 断血缘 |
| `spec` | `AgentSpec` | 必填 | 跑哪个 agent |
| `prompt` | `str \| Callable[[Ctx], str]` | 必填 | 说什么。可以是闭包,拿到 `ctx` 现算 |
| `resume_from` | `str \| None` | `None` | 续跑哪一步的会话。指向的步骤没产生会话时**抛 `ValueError`**,不是静默跳过 |
| `fork` | `bool` | `False` | 在 `resume_from` 的基础上分叉。**没有 `resume_from` 就无效** |
| `retries` | `int` | `0` | gate 没过时最多再试几次。`retries=0` = 只跑一轮 |
| `gate` | `Callable[[StepResult, Ctx], bool] \| None` | `None` | 判这一次算不算过。**可以是 async**。返回 `False` 视为失败。**每次尝试只调一次** —— 它可能有副作用(比如把确认书落盘),不该被重复触发 |
| `on_fail` | `str` | `"stop"` | `"stop"` / `"skip"` / `"continue"`,见下 |
| `when` | `Callable[[Ctx], bool] \| None` | `None` | 返回 `False` 则**整步跳过**:不产生 result、不进 `ctx["_results"]`。**可以是 async** |
| `on_reject` | `Callable[[StepResult, Ctx], str] \| None` | `None` | gate 没过时**下一轮说什么**。**可以是 async**。给了它重试语义就变了,见下 |
| `resume_prompt` | `str \| Callable[[Ctx], str] \| None` | `None` | 接续(而不是重头开始)时用的 prompt |
| `reduce` | `Callable[[StepResult, Ctx], str] \| None` | `None` | 决定 `ctx[name]` 放什么。默认放 `result.text` 原文。**必须是同步函数** |

| 方法 | 签名 | 说明 |
|---|---|---|
| `render` | `(ctx: Ctx, *, resuming: bool = False) -> str` | `resuming` 且有 `resume_prompt` 时用后者,否则用 `prompt`;是可调用对象就传 `ctx` 调它 |

**三种会话接法**(同一次运行内):

| 写法 | 效果 |
|---|---|
| `resume_from=None`(默认) | 新会话,只靠 prompt 里传入的上下文。便宜、隔离。**但 `Workflow(continuous=True)` 时会取跨进程血缘里同名步骤的会话** |
| `resume_from="上一步名"` | 续跑同一条会话,完整上下文。贵、连贯 |
| `resume_from="上一步名", fork=True` | 分叉,不污染原会话。复核 / 多方案并行用 |

**`on_reject` 改变重试语义**:

- 不给 → 下次尝试**重头跑**(同样的 prompt、同样的 `resume_from`)。
- 给了 → 下次尝试**续跑刚被否掉的那条会话**,prompt 换成它的返回值,`fork` 强制为 `False`。
- 返回空字符串 → 不打回,退化成重头跑。
- `result.session_id` 为 `None` → 也退化成重头跑。

**`on_fail` 三种取值**:

| 值 | 行为 |
|---|---|
| `"stop"`(默认) | 写 `ctx["_failed_at"] = name`,**中断整个 workflow** |
| `"skip"` | 跳到下一步,**`ctx[name]` 不写** —— 下游 `lambda ctx: ctx["某步"]` 会 `KeyError` |
| `"continue"` | `ctx[name] = result.text`,带着残缺结果往下走 |

无论过没过,`ctx["_results"][name] = result` 都会写;`result.session_id` 非空时还会写进
`ctx["_sessions"]` 并 `lineage.remember(...)`。

### `Workflow` {#workflow}

```python
@dataclass
class Workflow:
    steps: list[Step]
    name: str = "workflow"
    context: Ctx = field(default_factory=dict)
    channel: Any = None
    workbench: Any = None
    continuous: bool = True

    async def run(
        self,
        runtime: Runtime,
        *,
        on_event: Callable[[Event], None] | None = None,
        on_step: Callable[[Step, StepResult], None] | None = None,
    ) -> Ctx
```

按顺序跑一串 `Step`,返回最终的 `ctx`。`steps` 是位置参数,`Workflow([...])` 合法。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `steps` | `list[Step]` | 必填 | 按顺序执行 |
| `name` | `str` | `"workflow"` | 流程名 |
| `context` | `Ctx` | `{}` | 初始上下文字典。**同一个 `Workflow` 跑第二次时 ctx 是同一个 dict** |
| `channel` | `HumanChannel \| None` | `None` | 需要停下来问人时挂这里。`run()` 会自动把它的 `on_event` 接到同一出口,**仅当 `channel.on_event is None`**;驱动程序也靠这个字段知道该向谁回答 |
| `workbench` | `Workbench \| None` | `None` | 由 workflow 指定的工作台,好让驱动程序找到它 |
| `continuous` | `bool` | `True` | 同一个路径 = 同一段对话。落地是 [`Lineage`](#lineage) |

| `run()` 的参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `runtime` | `Runtime` | 必填,位置参数 | 用哪个运行时跑 |
| `on_event` | `Callable[[Event], None] \| None` | `None` | 事件出口,透传给每次 `Runtime.run` |
| `on_step` | `Callable[[Step, StepResult], None] \| None` | `None` | 每步跑完回调一次 |

!!! warning "`continuous=True` 是默认值,`resume_from=None` 不等于全新会话"
    开着接续时,`run()` 先 `Lineage.open(run_dir, workspace)`,再对每条记录逐个用
    `runtime.has_session(sid)` 验证还在库里,活着才灌进 `ctx["_sessions"]`。于是
    **`resume_from=None` 的步骤也会接着上次那条会话说** —— 进程被杀、机器重启也一样。

    要每次都是全新会话,显式写 `Workflow(..., continuous=False)`。
    另外:**步骤名是跨进程稳定的键,改了步骤名就等于断了血缘。**

`run()` 写进 ctx 的**私有键**(全部以 `_` 开头,不会和步骤名撞):

| 键 | 内容 |
|---|---|
| `_runtime` | 传进来的 `Runtime`。**gate 里派 agent 靠它** |
| `_on_event` | 事件出口。gate 里那个 agent 也要能打到 UI 上,否则界面全黑 |
| `_sessions` | `dict[步骤名, session_id]`,用 `setdefault` 取 |
| `_results` | `dict[步骤名, StepResult]` |
| `_lineage` | `Lineage` 对象。仅 `continuous=True` 且 runtime 有 `run_dir` + `workspace` 时才有 |
| `_woke` | `lineage.bump()` 的返回值,这是第几次唤醒 |
| `_aborted` | `StepAbort` 的消息 |
| `_failed_at` | `on_fail="stop"` 时失败的步骤名 |

`Event("step")` 的 payload:`{"index": i, "total": len(steps), "resumed": bool, "woke": int}`。

**重试标签**:第 0 次用 `step.name`;之后有 `on_reject` 用 `f"{name}#round{attempt+1}"`,
没有则 `f"{name}#retry{attempt}"`。manifest 里一眼能看出这一步是怎么走完的。
**带后缀的名字不进跨进程血缘** —— `Lineage.remember` 用的是原名。

`runtime.on_session` 只罩 `runtime.run` 这一句,用 `try/finally` 保证 gate 之前一定摘掉。
`prompt_cur` / `resume_cur` / `fork_cur` 是局部变量,不写回 `step` —— 同一个 `Step` 对象可能被跑第二次。

### `StepAbort` {#stepabort}

```python
class StepAbort(Exception): ...
```

由 `gate` 抛出 = **立刻停,不要再重试**。和"返回 `False`"的区别:`False` 是"这次不行,再来一轮";
`StepAbort` 是"再来也没用"。

抛出后:`ctx["_aborted"] = str(exc)`、`passed = False`、**跳出重试循环(不消耗剩余的 `retries`)**,
然后按普通失败走 `on_fail`(默认 `"stop"`)。

`with_goal` 在两处抛它:拿不到 `ctx["_runtime"]` 时,以及判定结果是 `unreachable` 而没人应答时。

### `clarify_step()` {#clarify-step}

```python
def clarify_step(
    channel: HumanChannel,
    *,
    brief_path: str | Path,
    prompt: str | Callable[[Ctx], str],
    name: str = "确认需求",
    spec: AgentSpec | None = None,
    instructions: str = "",
    always_ask: bool = False,
    on_fail: str = "stop",
    retries: int = 0,
    **spec_kw,
) -> Step
```

产出一个做[前置确认](glossary.md#前置确认)的 `Step`:问清需求 → 解析成 [`Brief`](#brief) →
四段齐全就冻结落盘。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `channel` | `HumanChannel` | 必填,位置参数 | 提问通道 |
| `brief_path` | `str \| Path` | 必填 | [需求确认书](glossary.md#需求确认书)落在哪。**必须落在真正被注入索引的那个工作台里** |
| `prompt` | `str \| Callable[[Ctx], str]` | 必填 | 人的原始诉求 |
| `name` | `str` | `"确认需求"` | 步骤名,同时是 `ctx` 里的键 |
| `spec` | `AgentSpec \| None` | `None` | 不给就用 `clarify(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | 追加给[确认者](glossary.md#确认者)的补充指令 |
| `always_ask` | `bool` | `False` | `True` = 每次都重新问,不管确认书在不在 |
| `on_fail` | `str` | `"stop"` | 同 `Step.on_fail` |
| `retries` | `int` | `0` | 四段没凑齐时再问几次 |
| `**spec_kw` | | | 直接透传给 [`clarify()`](#clarify-role),所以可以写 `can_read=False`、`max_budget_usd=...` |

产出的 `Step` 里各字段是这样填的:

- `resume_prompt = CLARIFY_RESUME`。
- `when`:`always_ask=True` → 恒 `True`;否则 `Brief.load(brief_path)` 齐全就把它灌进 ctx
  **然后返回 `False`(跳过)** —— 跳过也要灌,否则下游拿不到需求。
- `gate`:`Brief.parse(result.text)`,不全 → 写 `ctx[MISSING_KEY]` 并返回 `False`;
  齐全 → `b.write(brief_path)` 冻结,灌进 ctx,返回 `True`。
- `reduce`:返回 `ctx[BRIEF_KEY].prompt_block()`,**不是模型原文** —— 原文里可能夹着它多写的东西。
- `resume_from` **保持默认 `None`**:下一步是新会话,只拿到确认书,拿不到那段问答。
  澄清对话**从来没进过**协调者的上下文,不是进去之后被剪掉的。

灌进 ctx 的三处:`ctx[BRIEF_KEY] = b`、`ctx[name] = b.prompt_block()`、`ctx.pop(MISSING_KEY, None)`。

| 常量 | 值 | 说明 |
|---|---|---|
| `BRIEF_KEY` | `"_brief"` | `ctx[BRIEF_KEY]` 是 `Brief` 对象;`ctx[step.name]` 是它的 `prompt_block()` |
| `MISSING_KEY` | `"_brief_missing"` | 确认失败时缺哪几段(中文段名),给 UI 显示 |
| `CLARIFY_RESUME` | 一段中文提示词 | "接着刚才那次没问完的需求确认继续 —— **不是重新开始**……"。不给这句,接续会把原始诉求当新任务重发,确认者可能把问过的重问一遍 |

### `goal_step()` {#goal-step}

```python
def goal_step(
    channel: HumanChannel,
    *,
    goal_path: str | Path,
    brief_key: str = "确认需求",
    name: str = "设定目标",
    spec: AgentSpec | None = None,
    instructions: str = "",
    always_set: bool = False,
    on_fail: str = "stop",
    retries: int = 0,
    **spec_kw: Any,
) -> Step
```

产出一个**设定目标**的 `Step`:让[判定者](glossary.md#判定者)读确认书,写出目标 + 判定清单,
解析成 [`Goal`](#goal) 后冻结落盘。和 `clarify_step` 是同一个形状。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `channel` | `HumanChannel` | 必填,位置参数 | 提问通道 |
| `goal_path` | `str \| Path` | 必填 | 目标文件落在哪 |
| `brief_key` | `str` | `"确认需求"` | 从 `ctx[brief_key]` 取确认书原文塞进 prompt。**取不到就是 `"(没有确认书)"`** |
| `name` | `str` | `"设定目标"` | 步骤名 |
| `spec` | `AgentSpec \| None` | `None` | 不给就用 `judge(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | 追加指令 |
| `always_set` | `bool` | `False` | `True` = 重推清单,不管目标文件在不在 |
| `on_fail` | `str` | `"stop"` | 同上 |
| `retries` | `int` | `0` | 同上 |
| `**spec_kw` | | | 透传给 [`judge()`](#judge-role) |

**没有 `can_run` 形参** —— 想让设目标的判定者能跑命令,只能通过 `**spec_kw` 传 `can_run=True`。
不传的话它拿不到 `Bash`,`JUDGE_RULES` 里"先看清楚你在什么环境"那条执行不了。

`gate` 除了解析和冻结,还额外做一件事:目标里有 `[此环境无法验证:…]` 条目时,**当场**通过
`ctx["_on_event"]` 发一个 `Event("task", payload={"unverifiable", "total", "path"})` 提醒 ——
这些条目的命运在设目标这一刻就定了,等到判定时已经花掉整轮干活的钱。

**没有设 `resume_prompt`** —— 设定目标本来就该重发全文确认书。

| 常量 | 值 | 说明 |
|---|---|---|
| `GOAL_KEY` | `"_goal"` | `ctx[GOAL_KEY]` 是 `Goal` 对象;`ctx[step.name]` 是 markdown |
| `VERDICT_KEY` | `"_verdict"` | 最近一次 [`Verdict`](#verdict),给 UI 用 |
| `ROUND_KEY` | `"_goal_rounds"` | 判定跑了几轮 |

### `with_goal()` {#with-goal}

```python
def with_goal(
    step: Step,
    channel: HumanChannel,
    *,
    goal_path: str | Path,
    spec: AgentSpec | None = None,
    rounds: int = 3,
    instructions: str = "",
    can_run: bool = False,
    name: str | None = None,
    **spec_kw: Any,
) -> Step
```

给一个已有的 `Step` 套上[目标看守](glossary.md#目标看守):每轮结束后由判定者独立判定,
没达成就打回去接着做。

产出是 `replace(step, retries=max(0, rounds - 1), gate=<新 gate>, on_reject=<新 on_reject>)` ——
用 `dataclasses.replace` 而不是逐字段重建,重建过一次就漏了 `resume_prompt`,**而且不报错**,
只是接续时把整份确认书又发了一遍。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `step` | `Step` | 必填,位置参数 | 被看守的那一步 |
| `channel` | `HumanChannel` | 必填,位置参数 | 判不动时向人求助的通道 |
| `goal_path` | `str \| Path` | 必填 | 目标文件,`ctx[GOAL_KEY]` 不齐全时从这里读 |
| `spec` | `AgentSpec \| None` | `None` | 不给就用 `judge(label, channel, instructions=..., can_run=can_run, **spec_kw)` |
| `rounds` | `int` | `3` | **总轮数,不是额外轮数**:`rounds=3` → `retries=2` → 最多跑三轮活。`rounds=1` = 跑一轮、判一次、判不过就失败 |
| `instructions` | `str` | `""` | 追加给判定者的指令 |
| `can_run` | `bool` | `False` | 判定者能不能跑 `Bash` |
| `name` | `str \| None` | `None` | 判定者的名字,默认 `f"{step.name}·判定"` |
| `**spec_kw` | | | 透传给 `judge()` |

`gate` 是 **async** 的,流程:

1. `ctx["_runtime"]` 缺失 → **抛 `StepAbort`**("拿不到 Runtime,无法判定目标")。**别假装通过。**
2. `ctx[ROUND_KEY] += 1`。
3. 取目标:优先 `ctx[GOAL_KEY]` 里齐全的 `Goal`,否则 `Goal.load(goal_path)`,否则空 `Goal()`。
4. `await rt.run(judger, VERIFY_PROMPT..., step_name=f"{label}#{轮次}", on_event=...)`。
   **判定者是独立的一次 `Runtime.run`,`resume` 恒为 `None` —— 永远是新会话**;`step_name` 带轮次,
   所以不进跨进程血缘。
5. `Verdict.parse(vr.text)` 写进 `ctx[VERDICT_KEY]`。
6. `v.achieved` → 返回 `True`。
7. 不是 `unreachable`(含 `v.ok=False` 的含糊情况)→ 含糊时补一句默认 reason,返回 `False`。
   **含糊一律按未达成** —— 不能让一句"看起来可以"把活收掉。
8. `unreachable` → `await channel.ask(...)` 问人,三个选项:
   - 没人应答(`a.state != "answered"`)→ **抛 `StepAbort`**。继续空转是最贵的选择。
   - 「接受这个结果,就这样往下走」→ 返回 `True`。
   - 「修改目标」→ 再问一次新目标,`g.amend(...).write(goal_path)`、更新 `ctx[GOAL_KEY]`,返回 `False`。
   - 其余(含人自己打的自由回答)→ 当"你判断错了",把人的说法记进 `v.reason`,返回 `False`。

`on_reject` 是**同步**的:返回 `ctx[VERDICT_KEY].feedback()`,没有 `Verdict` 就返回 `""`
(退化成重头跑)。

### `starter_flow()` {#starter-flow}

```python
def starter_flow(
    ask: str,
    *,
    workspace: str | Path = ".",
    run_dir: str | Path = "runs",
    new: bool = False,
    isolate: bool = False,
    clarify_only: bool = False,
    goal: bool = True,
    rounds: int = 3,
    judge_can_run: bool = False,
    max_asks: int | None = None,
    timeout_s: float | None = 1800.0,
    instructions: str = "",
    worker_prompt: str = "你负责实现。每改一处就跑一次验证,别攒到最后。",
    brief_name: str = "需求.md",
    goal_name: str = "目标.md",
    log_name: str = "问答记录.md",
) -> Workflow
```

装配一个开箱能跑的三步流程:**确认需求 → 设定目标 → 干活**(带目标看守)。命令行 `flower` 用的就是它。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `ask` | `str` | 必填,位置参数 | 一句诉求。**唤醒时它不是新任务,是"又说的一句话"** |
| `workspace` | `str \| Path` | `"."` | 工作区 |
| `run_dir` | `str \| Path` | `"runs"` | 运行目录 |
| `new` | `bool` | `False` | `True` = 归档血缘 + 确认书 + 目标(三个一起收),从头开始 |
| `isolate` | `bool` | `False` | 给执行者开 worktree [隔离](glossary.md#隔离)。工作台随之挪到 `<ws>.parent/.flower-<ws.name>` |
| `clarify_only` | `bool` | `False` | 只返回含确认步骤的 Workflow |
| `goal` | `bool` | `True` | 装不装[目标看守](glossary.md#目标看守)。`False` = 干活那步跑完就算完 |
| `rounds` | `int` | `3` | 透传给 `with_goal(rounds=)`,总轮数 |
| `judge_can_run` | `bool` | `False` | 透传给 `with_goal(can_run=)` |
| `max_asks` | `int \| None` | `None` | 透传给 `HumanChannel`,`None` = 不限次 |
| `timeout_s` | `float \| None` | `1800.0` | 透传给 `HumanChannel`。`0` = 全自动,所有提问立刻落空 |
| `instructions` | `str` | `""` | 追加给确认者的指令 |
| `worker_prompt` | `str` | 见签名 | 执行者的 system prompt |
| `brief_name` | `str` | `"需求.md"` | 确认书文件名,落在 `<workbench.notes>/` |
| `goal_name` | `str` | `"目标.md"` | 目标文件名,同上 |
| `log_name` | `str` | `"问答记录.md"` | 问答记录文件名,同上 |

固定装配:

```python
Workflow(name="starter", channel=ch, workbench=wb, steps=[...])
# ch = HumanChannel(log_path=<notes>/问答记录.md, amend_path=<brief_path>,
#                   max_asks=max_asks, timeout_s=timeout_s)
# 协调者 = coordinator("协调者", "", {"coder": worker(..., isolate=isolate)}, channel=ch)
```

行为分支:

- `isolate=True` 且 workspace 不是 git 仓库 → **抛 `ValueError`**,不等到 `Agent` 工具报错才发现
  (那时钱已经花了)。
- **唤醒判定**:`Brief.load(brief_path)` 存在且 `complete()` 就算唤醒。不是唤醒且 `ask` 为空 →
  **抛 `ValueError("要给一句诉求,例如 flower '帮我做一个 X'")`**。
- 唤醒时那句话同时落到**三个地方**,少一个都会静默失效:追进确认书
  (`ch.amend(said, label="唤醒时追加")`,已在文件里就不重复写)、
  让 `goal_step(always_set=True)` 重推清单(不重推的话判定者读的还是老目标)、
  直接送到协调者面前(它的上下文里是**旧**目标,不给会按旧标准干然后被按新标准判)。

### `wake_state()` {#wake-state}

```python
def wake_state(
    workspace: str | Path = ".",
    *,
    run_dir: str | Path = "runs",
    isolate: bool = False,
    brief_name: str = "需求.md",
    goal_name: str = "目标.md",
) -> dict
```

**起跑之前的只读探测,一个字节都不写。** 用来在真正开跑前告诉人"这是接着上次,还是从头开始"。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `workspace` | `str \| Path` | `"."` | 工作区,位置参数 |
| `run_dir` | `str \| Path` | `"runs"` | 运行目录 |
| `isolate` | `bool` | `False` | 决定工作台位置,必须和 `starter_flow` 传一样的值 |
| `brief_name` | `str` | `"需求.md"` | 确认书文件名 |
| `goal_name` | `str` | `"目标.md"` | 目标文件名 |

返回的 dict:

| 键 | 类型 | 说明 |
|---|---|---|
| `waking` | `bool` | 确认书存在且四段齐全 |
| `brief` | `Path` | `<workbench.notes>/需求.md` |
| `goal` | `Path` | `<workbench.notes>/目标.md` |
| `checks` | `int` | 目标清单条数,没有目标时 `0` |
| `woke` | `int` | `Lineage.woke`,已经唤醒过几次 |
| `steps` | `dict` | `Lineage.steps` 的拷贝,步骤名 → `session_id` |

工作台位置**只在这里和 `starter_flow` 里定义一次**:`isolate=True` → `<ws>.parent/.flower-<ws.name>`
(仓库外);否则 `<ws>/.flower`。驱动程序想知道确认书在哪也走这个函数 —— 自己拼路径拼错了不报错,
只是静默失效。

---

## 角色工厂 {#角色工厂}

源码:[`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py)

五个角色都是工厂函数。每个角色 = **一段注入的规则文本 + 一组工具 + 一组 hook**。
`worker()` 产出的是 SDK 的 `AgentDefinition`(派给 subagent 用),另外四个产出 [`AgentSpec`](#agentspec)
(自己起一条会话)。

角色本身**不挂 hook** —— 拦工具的活是 `Runtime._attempt` 按 `spec.delegate_only` 自动装的,
见 [hook 层](#hook)。

内部工具组常量(未导出,但决定了默认值):

```python
COORDINATOR_TOOLS = ["Agent", "TodoWrite", "Read"]
WEB_TOOLS         = ["WebFetch", "WebSearch"]
WORKER_TOOLS      = ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebFetch", "WebSearch"]
```

### `coordinator()` {#coordinator}

```python
def coordinator(
    name: str,
    instructions: str,
    workers: dict[str, AgentDefinition],
    *,
    channel: Any = None,
    can_read: bool = True,
    glance: bool = True,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
    permission_mode: str = "acceptEdits",
    compact: Any = None,
    hooks: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> AgentSpec
```

造[主线程](glossary.md#主线程)上那个[协调者](glossary.md#协调者):拆解任务、派活、读报告、做决策,
**但不动手**。前三个参数是位置参数。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `name` | `str` | 必填 | 角色名,也是默认的步骤名 |
| `instructions` | `str` | 必填 | 领域指令。最终是 `f"{COORDINATOR_RULES}\n{instructions}".strip()` |
| `workers` | `dict[str, AgentDefinition]` | 必填 | 手下有哪些角色,落到 `AgentSpec.agents` |
| `channel` | `HumanChannel \| None` | `None` | 给了就同时追加 `inbox` **和** `ask` 两个工具,并设 `mcp_servers` |
| `can_read` | `bool` | `True` | `True` → `["Agent", "TodoWrite", "Read"]`;`False` → 去掉 `Read` |
| `glance` | `bool` | `True` | 追加 `"Bash"`,并设 `AgentSpec.glance`。**具体能跑什么由 `delegate_guard` 把关**,不是靠这里 |
| `model` | `str \| None` | `None` | 模型 |
| `effort` | `str \| None` | `None` | 思考强度 |
| `max_turns` | `int \| None` | `None` | 轮数上限 |
| `max_budget_usd` | `float \| None` | `None` | [预算](glossary.md#预算)上限 |
| `permission_mode` | `str` | **`"acceptEdits"`** | 权限模式。**注意这个默认值** —— 把它传给 `clarify()`/`judge()` 会拆掉那两个角色的保护 |
| `compact` | `CompactPolicy \| None` | `None` | 给了就不会被 `Runtime` 强制改成 `no_summary` |
| `hooks` | `dict[str, Any] \| None` | `None` | 额外 hook,会和 `workbench_hooks` 合并 |
| `env` | `dict[str, str] \| None` | `None` | 额外环境变量 |

产出的 `AgentSpec` 里固定的三项:`delegate_only=True`、`agents=workers`、
`workbench` 保持 `AgentSpec` 的默认 `True`。

源码里明确写着**不要用 `disallowed_tools` 实现"只协调不动手"** —— 那是会话级的,
会把 subagent 的 `Bash`/`Write` 一起禁掉,见 [`AgentSpec`](#agentspec) 那条警告。
正确做法就是这里的 `delegate_only=True` + `allowed_tools` 不给,
再由 [`delegate_guard`](#delegate-guard) 按 `agent_id` 只拦主线程。

`channel` 给了就是**两个工具一起来**,不是可选的:MCP server 一挂就是两个都在,而
`allowed_tools` 不排他,列不列都调得动。无人值守时每次 `ask` 都会卡满 `timeout_s` ——
那种场合用 `HumanChannel(timeout_s=0)`。

### `worker()` {#worker}

```python
def worker(
    description: str,
    prompt: str,
    *,
    tools: list[str] | None = None,
    model: str = "inherit",
    effort: str | int | None = None,
    max_turns: int | None = None,
    permission_mode: str | None = None,
    skills: list[str] | None = None,
    discipline: bool = True,
    isolate: bool = False,
) -> AgentDefinition
```

造真正干活的 [subagent](glossary.md#subagent) 定义。前两个参数是位置参数。
返回的是 SDK 的 `AgentDefinition`,直接塞进 `coordinator(workers={...})`。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `description` | `str` | 必填 | **协调者用来选人的依据** —— 写清楚"什么活派给它" |
| `prompt` | `str` | 必填 | 它的 system prompt。`discipline=True` 时拼成 `f"{prompt}\n\n{WORKER_RULES}"` |
| `tools` | `list[str] \| None` | `None` | `None` → `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str` | **`"inherit"`** | 干活的不该被降级 |
| `effort` | `str \| int \| None` | `None` | 思考强度 |
| `max_turns` | `int \| None` | `None` | 落到 SDK 的 **`maxTurns`**(驼峰) |
| `permission_mode` | `str \| None` | `None` | 落到 SDK 的 **`permissionMode`**(驼峰) |
| `skills` | `list[str] \| None` | `None` | 允许它用哪些 skill |
| `discipline` | `bool` | `True` | 拼不拼 `WORKER_RULES` 那段汇报纪律 |
| `isolate` | `bool` | `False` | 打[隔离](glossary.md#隔离)标记,走 `isolated()`,**不是 `AgentDefinition` 的字段** |

`isolate=True` 要求 workspace 是 git 仓库,否则 `Agent` 工具直接报 `"not in a git repository"`,
**不会静默退化**。而且标记是 Python 属性 —— 对 `AgentDefinition` 做 `dataclasses.replace()`
会丢掉它,隔离静默失效。

### `clarify()` {#clarify-role}

```python
def clarify(
    name: str,
    channel: Any,
    *,
    instructions: str = "",
    can_read: bool = True,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
) -> AgentSpec
```

造[确认者](glossary.md#确认者):动手之前把需求问清楚,不做事、只提问,最后输出恰好四段。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `name` | `str` | 必填 | 角色名,位置参数 |
| `channel` | `HumanChannel` | 必填 | 提问通道,位置参数 |
| `instructions` | `str` | `""` | 补充指令,拼在 `CLARIFIER_RULES` 之后 |
| `can_read` | `bool` | `True` | `True` 时追加 `Read` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str \| None` | `None` | 模型 |
| `effort` | `str \| None` | `None` | 思考强度 |
| `max_turns` | `int \| None` | `None` | **不限轮数** |
| `max_budget_usd` | `float \| None` | `None` | 预算上限 |

产出的 `AgentSpec`:`allowed_tools = [channel.tool_name] + (可读时那五个)`、
`mcp_servers = channel.mcp_servers()`、`workbench=False`(它没有写工具,索引对它没意义)、
`permission_mode` 继承 `AgentSpec` 的默认 `"default"`。
**没有 `Write` / `Edit` / `Bash` / `Agent`,也没有 `inbox`**(和协调者不同)。

!!! warning "`max_turns` 设小数字会让不限次数的提问变成空话"
    每次提问就是一轮。`max_turns=16` 等于"最多问十几个",通道里那句"没有轮数上限"当场作废。

    要放开提问就得**同时**放开两处:`HumanChannel.max_asks`(默认已是 `None` = 不限)
    和 `max_turns`(默认已是 `None`)。

### `judge()` {#judge-role}

```python
def judge(
    name: str,
    channel: Any,
    *,
    instructions: str = "",
    can_run: bool = False,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
) -> AgentSpec
```

造[判定者](glossary.md#判定者):要么开跑前设定目标,要么每轮结束后判定这一轮。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `name` | `str` | 必填 | 角色名,位置参数 |
| `channel` | `HumanChannel` | 必填 | 提问通道,位置参数 |
| `instructions` | `str` | `""` | 补充指令,拼在 `JUDGE_RULES` 之后 |
| `can_run` | `bool` | `False` | `True` 时白名单里加 `Bash`,`whitelist_guard` 随之放行 `Bash`、仍拦 `Write`/`Edit` |
| `model` | `str \| None` | `None` | 模型 |
| `effort` | `str \| None` | `None` | 思考强度 |
| `max_turns` | `int \| None` | `None` | 轮数上限 |
| `max_budget_usd` | `float \| None` | `None` | 预算上限 |

产出的 `AgentSpec`:`allowed_tools = [channel.tool_name, "Read", "Glob", "Grep"]` + (`can_run` 时)`["Bash"]`、
`workbench=False`、其余同 `clarify()`。**没有 `Write` / `Edit` / `Agent`,也没有 `inbox`。**

**取舍**:`can_run=True` 判定更硬(能真跑验收命令),代价是判定者因此能改动工作区 ——
`Bash` 本身就能写文件。要绝对中立的判定就别开。

### `oracle()` {#oracle}

```python
def oracle(
    name: str = "旁路问答",
    *,
    instructions: str = "",
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = 12,
    max_budget_usd: float | None = 0.5,
) -> AgentSpec
```

造[旁路顾问](glossary.md#旁路顾问):运行还在跑的时候问它"现在到哪了",它看一眼最近事件和工作台
再回答。**它说的话不会进入那次运行的上下文。**

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `name` | `str` | `"旁路问答"` | 角色名,位置参数 |
| `instructions` | `str` | `""` | 补充指令,拼在 `ORACLE_RULES` 之后 |
| `model` | `str \| None` | `None` | 模型 |
| `effort` | `str \| None` | `None` | 思考强度 |
| `max_turns` | `int \| None` | **`12`** | 默认带闸 |
| `max_budget_usd` | `float \| None` | **`0.5`** | 默认带闸。这是"顺口问一句",不该失控 |

产出的 `AgentSpec`:`allowed_tools = ["Read", "Glob", "Grep"]`(**没有 channel** —— 它不提问,
只回答)、`workbench=True`(**五个角色里唯一一个非协调者却开工作台的** —— 它就是要去读那些产出和笔记)。

### 五份规则文本 {#rules}

五个常量都在 `__all__` 里,可以直接 `import` 出来读、拼、改。

| 常量 | 注入给谁 | 注入方式 | 要点 |
|---|---|---|---|
| `COORDINATOR_RULES` | `coordinator()` | `f"{RULES}\n{instructions}".strip()` | 你是"一个会用 Claude Code 的人",不是执行者;不能写文件/改代码/跑测试;`Bash` 只够"看一眼"且结果会过期;**[任务书](glossary.md#任务书)只写这次任务专属的东西**;唯一还需交代的规矩是"工作台在哪 + 长产出写 `artifacts/` + 回话只给路径";每完成一个阶段性动作查一次 `inbox`;`ask` 会阻塞,只在真正岔路口用 |
| `WORKER_RULES` | `worker()` | 拼在 subagent 的 `prompt` **之后** | 回话格式 **结论 / 依据 / 产出 / 未验证**,不超过 30 行;禁止贴文件内容、命令输出、日志、diff 原文;禁止复述试错过程;动手前先看 `.flower/scripts/`。**故意没写"长产出写 `artifacts/`"** —— 真实路径由 `Workbench` 生成,写死会错 |
| `CLARIFIER_RULES` | `clarify()` | `f"{RULES}\n{instructions}".strip()` | 不做事,只问清需求;**没有次数限制,问到清楚为止**;人可能不在,超时就自己判断并写进「未知与假设」;输出**恰好四段**;不要写代码、不要贴文件内容 |
| `JUDGE_RULES` | `judge()` | `f"{RULES}\n{instructions}".strip()` | 两件事二选一。**设目标**:每条清单必须能当场验证,清单长度由失败方式数量决定,**边界不是判定项**,验不了的条目结尾加 `[此环境无法验证:原因]`。**判定这一轮**:输出**恰好三段**,判的是**产出物不是源码**,默认不信"做完了","没做到"与"这里没法验"是两个不同结论,后者**绝对不许判通过** |
| `ORACLE_RULES` | `oracle()` | `f"{RULES}\n{instructions}".strip()` | 一条旁路;那次运行还在跑,你不打断也不参与;**只读**;答完即弃,你说的话不会进入那次运行的上下文;手上只有"最近事件窗口"和"工作台";先看再答,答不了就说答不了,简短 |

---

## agent 定义 {#agent-定义}

源码:[`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)

`AgentSpec` 是一个专项 agent 的完整声明,`build_options` 把它编译成 SDK 的 `ClaudeAgentOptions`。
[角色工厂](#角色工厂)产出的就是 `AgentSpec` —— 需要工厂之外的组合时,直接构造它。

### `AgentSpec` {#agentspec}

```python
@dataclass
class AgentSpec:
    name: str
    instructions: str
    allowed_tools: list[str] = field(default_factory=lambda: ["Read", "Glob", "Grep"])
    disallowed_tools: list[str] = field(default_factory=list)
    model: str | None = None
    effort: str | None = None
    max_turns: int | None = None
    max_budget_usd: float | None = None
    permission_mode: str = "default"
    agents: dict[str, Any] | None = None
    mcp_servers: dict[str, Any] = field(default_factory=dict)
    hooks: dict[str, Any] | None = None
    compact: CompactPolicy | None = None
    env: dict[str, str] = field(default_factory=dict)
    glance: bool = False
    workbench: bool = True
    delegate_only: bool = False
```

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `name` | `str` | 必填 | 角色名。也是 `Runtime.run` 的默认 `step_name`,和 `whitelist_guard` 拒绝文案里的自称 |
| `instructions` | `str` | 必填 | 领域指令。**[叠加](glossary.md#叠加)在 Claude Code 原生 system prompt 之后,不是替换** |
| `allowed_tools` | `list[str]` | `["Read", "Glob", "Grep"]` | **免审批清单,不是排他白名单** —— 模型照样能调不在里面的工具。排他靠 [`whitelist_guard`](#whitelist-guard) |
| `disallowed_tools` | `list[str]` | `[]` | **会话级**。见下面的警告 |
| `model` | `str \| None` | `None` | 模型 |
| `effort` | `str \| None` | `None` | 思考强度 |
| `max_turns` | `int \| None` | `None` | 轮数上限 |
| `max_budget_usd` | `float \| None` | `None` | [预算](glossary.md#预算)上限 |
| `permission_mode` | `str` | `"default"` | 权限模式 |
| `agents` | `dict[str, Any] \| None` | `None` | subagent 定义表,值是 `AgentDefinition` |
| `mcp_servers` | `dict[str, Any]` | `{}` | MCP server 表。`HumanChannel.mcp_servers()` 直接填这里 |
| `hooks` | `dict[str, Any] \| None` | `None` | 额外 hook,`Runtime` 会用 `merge_hooks` 和自己那套合并 |
| `compact` | `CompactPolicy \| None` | `None` | 给了就不会被 `Runtime` 强制改成 `no_summary` |
| `env` | `dict[str, str]` | `{}` | 注入子进程的环境变量。`compact.env()` 会 update 上去 |
| `glance` | `bool` | `False` | 允许主 agent 自己跑"只看一眼"的 `Bash`。放行哪些由 [`is_ephemeral`](#is-ephemeral) 决定,结果会被 `EphemeralPolicy` 标记过期 |
| `workbench` | `bool` | `True` | 是否把工作台索引注入这个 agent 的 system prompt。**没有写工具的角色要关掉**(`clarify()` / `judge()` 默认就是 `False`) |
| `delegate_only` | `bool` | `False` | 只协调不动手。`True` 时 `Runtime` 装 `delegate_guard`、**不装** `whitelist_guard` |

!!! warning "`disallowed_tools` 是会话级的,会连 subagent 一起禁掉"
    实测报错原文:`"Bash is disabled for this session, in subagents as well as here"`。
    也就是说,想让协调者不动手而用了 `disallowed_tools=["Bash"]`,派出去的执行者也跑不了命令 ——
    整个运行就废了。

    要"只协调不动手",用 `delegate_only=True` + `allowed_tools` 不给,让
    [`delegate_guard`](#delegate-guard) 按 `agent_id` 只拦主线程。

### `build_options()` {#build-options}

```python
def build_options(
    spec: AgentSpec,
    *,
    cwd: str | Path | None = None,
    session_store: SessionStore | None = None,
    resume: str | None = None,
    fork: bool = False,
    resume_at: str | None = None,
    use_plugin: bool = True,
    portable: bool = True,
    add_dirs: list[str] | None = None,
    flush: str = "eager",
    prelude: str = "",
) -> ClaudeAgentOptions
```

把 `AgentSpec` 编译成 SDK 的 `ClaudeAgentOptions`。`Runtime._attempt` 内部调的就是它;
自己驱动 SDK(不用 `Runtime`)时也从这里进。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `spec` | `AgentSpec` | 必填,位置参数 | 要编译的声明 |
| `cwd` | `str \| Path \| None` | `None` | 非 `None` 才写入 `cwd` |
| `session_store` | `SessionStore \| None` | `None` | 非 `None` 才写入 `session_store` 和 `session_store_flush` |
| `resume` | `str \| None` | `None` | 续跑哪条会话 |
| `fork` | `bool` | `False` | 落成 `fork_session`。**嵌在 `if resume:` 里** |
| `resume_at` | `str \| None` | `None` | 落成 `resume_session_at`。**同样嵌在 `if resume:` 里** |
| `use_plugin` | `bool` | `True` | `True` 且 `PLUGIN_DIR` 存在 → `plugins=[{"type": "local", "path": ...}]` |
| `portable` | `bool` | `True` | `True` → `setting_sources=[]`;`False` → `["project"]` |
| `add_dirs` | `list[str] \| None` | `None` | 额外授权的目录。**工作台在工作区外时必须给** |
| `flush` | `str` | `"eager"` | 落成 `session_store_flush` |
| `prelude` | `str` | `""` | 追加在 `instructions` 之后的一段(工作台索引走这里) |

映射关系:

| 产出的 option 键 | 值 |
|---|---|
| `system_prompt` | `{"type": "preset", "preset": "claude_code", "append": spec.instructions [+ "\n\n" + prelude]}` |
| `allowed_tools` / `disallowed_tools` / `permission_mode` | 直接取自 `spec` |
| `setting_sources` | `[]`(可移植)或 `["project"]` |
| `plugins` | 仓库根的 `plugin/` 目录存在时才有 |
| `cwd` / `add_dirs` | 非空才写 |
| `session_store` / `session_store_flush` | `session_store` 非 `None` 才写 |
| `model` `effort` `max_turns` `max_budget_usd` `agents` `mcp_servers` `hooks` | 各自非空才写入 |
| `env` | `dict(spec.env)` 再 `update(spec.compact.env())` |
| `resume` / `fork_session` / `resume_session_at` | **只有 `resume` 为真时才生效** |

`PLUGIN_DIR` 是仓库根的 `plugin/`(相对 `flower/core/agent.py` 往上三层)。pip 装完这个目录未必存在,
代码用 `is_dir()` 判过。

!!! warning "`fork=True` 不给 `resume` 时静默无效"
    `fork_session` 和 `resume_session_at` 都嵌在 `if resume:` 里 —— 不给 `resume` 就完全不生效,
    **也不报错**。同理 `Runtime.run(resume_at=...)` 只在给了 `resume` 时才起作用,
    而 **`Workflow` 从不传 `resume_at`**:要按消息回滚只能直接调 `Runtime.run`。

### `CompactPolicy` {#compactpolicy}

```python
@dataclass
class CompactPolicy:
    mode: str = "auto"
    window: int | None = None

    def env(self) -> dict[str, str]: ...
```

auto-[压缩](glossary.md#压缩)的开关面板,产物是一组要注入子进程的环境变量。
压缩算法本身在 harness 二进制里改不了,能改的只有"触不触发"。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `mode` | `str` | `"auto"` | `"auto"` = 什么都不设,阈值 = 窗口 − 33k;`"no_summary"` → `DISABLE_AUTO_COMPACT=1`;`"off"` → `DISABLE_COMPACT=1`(连 `/compact` 一起关)。**其它值抛 `ValueError`**,不是静默忽略 |
| `window` | `int \| None` | `None` | 非 `None` → `CLAUDE_CODE_AUTO_COMPACT_WINDOW=<str(window)>`。CLI 侧限制 100k–1M,设小于 100k 会被抬到 100k |

| 方法 | 签名 | 说明 |
|---|---|---|
| `env` | `() -> dict[str, str]` | 产出环境变量。**非法 `mode` 是在这里抛 `ValueError` 的,不是构造时** —— 它由 `build_options` 调用,所以错误暴露在 `Runtime.run` 里 |

### `HandoffPolicy` {#handoffpolicy}

```python
@dataclass
class HandoffPolicy:
    enabled: bool = True
    window: int = field(default_factory=default_window)
    headroom: int = 50_000
    max_generations: int = 8

    @property
    def at(self) -> int: ...        # max(10_000, window - headroom)
    @property
    def warn_at(self) -> int: ...   # max(1_000, at - 20_000)
```

上下文快满时"写[交接书](glossary.md#交接书)换新会话"而不是压缩的策略对象。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `enabled` | `bool` | `True` | 关掉就退回 auto-compact |
| `window` | `int` | `default_window()` | 认为模型的上下文窗口有多大 |
| `headroom` | `int` | `50_000` | 留多少余量。理由:auto-compact 在窗口 −33k 触发,换代必须赶在它之前,而"写交接"本身还要跑一轮 |
| `max_generations` | `int` | `8` | 一步最多换几代。**这是防跑飞的闸,不是容量规划** |

| 属性 | 类型 | 说明 |
|---|---|---|
| `at` | `@property -> int` | 换代阈值 `max(10_000, window - headroom)`。**有 10k 下限** —— 再低连交接都写不出来 |
| `warn_at` | `@property -> int` | 逼近提醒位置 `max(1_000, at - 20_000)`,每代只发一次 |

!!! warning "`window` 配小了会无限换代烧钱"
    若 `at` 低于该角色的**启动地板**(协调者实测约 34k),每条新会话一开口就越线;而
    **换代不吃重试额度**(`attempt -= 1`),于是无限空转。唯一的闸是 `max_generations=8`,
    撞上后 `error` 会换成一句诊断,提示把 `window` 调大或关掉换代。

### `default_window()` {#default-window}

```python
def default_window() -> int
```

按环境变量 `ANTHROPIC_MODEL` 或 `ANTHROPIC_DEFAULT_OPUS_MODEL` 的**模型名字符串**猜上下文窗口:

| 条件 | 返回 |
|---|---|
| 名字里有独立的 `1m` 词(正则 `(?:^\|[^a-z0-9])1m(?:[^a-z0-9]\|$)`) | `1_000_000` |
| 名字里含 `haiku` | `200_000` |
| 其余(**包括两个变量都没设**) | `1_000_000` |

**默认取积极值**。判大了不是硬错:API 会以 `prompt is too long` 退回,`Runtime` 认这个信号
(内部的 `is_overflow`)并当场换代 —— 但那一代的交接是降级版本。

---

## 文书 {#文书}

源码:[`brief.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/brief.py) ·
[`handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
[`goal.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/goal.py)

四个 dataclass,都是"把模型的一段回话解析成固定几段,再落盘"。共同的形状:
`parse()` 解析、`missing()` / `complete()` 查齐不齐、`to_markdown()` 给人看、
`prompt_block()` 给下游模型看、`write()` / `load()` 落盘与读回。

### `Brief` {#brief}

```python
@dataclass
class Brief:
    goal: str = ""
    accept: str = ""
    bounds: str = ""
    unknowns: str = ""
    path: Path | None = field(default=None, compare=False)
```

[需求确认书](glossary.md#需求确认书),**恰好四段**,固定顺序
`goal` → `accept` → `bounds` → `unknowns`,中文段名分别是「目标」「验收标准」「边界」「未知与假设」。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `goal` | `str` | `""` | 目标 |
| `accept` | `str` | `""` | 验收标准 |
| `bounds` | `str` | `""` | 边界 |
| `unknowns` | `str` | `""` | 未知与假设 |
| `path` | `Path \| None` | `None` | 落盘位置。`compare=False`,不参与相等判断 |

| 方法 | 签名 | 说明 |
|---|---|---|
| `missing` | `() -> list[str]` | 缺失段的**中文名**,可直接显示 |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Brief` | 从模型回话解析四段。**先剥围栏代码块**,解析不到的留空 |
| `to_markdown` | `() -> str` | 带抬头元信息的完整文书,空段写 `"(未填)"` |
| `prompt_block` | `() -> str` | 喂下游用的紧凑版,**只含非空段**,无元信息 |
| `write` | `(path: str \| Path) -> Path` | 建父目录、写盘、把 `self.path` 设为 resolve 后的路径并返回 |
| `load` | `@classmethod (path: str \| Path) -> Brief \| None` | 文件不存在或 `OSError` 返回 `None`。**会把 `"(未填)"` 占位还原成空串** |

解析规则(易错点集中处):

- 剥围栏时**遇到未闭合的 ``` 或 `~~~` 就从它开始整段丢弃** —— 实测确认者会把整份代码贴进回话。
  模型输出被截断时,后面的段全部解析不出来,于是 `complete()` 为 `False`,gate 打回重来。
- 标题正则容忍 `## 目标` / `**目标**` / `目标:` / `3. 边界`,也容忍标题后直接跟正文。
- 别名表按长度倒序编译,否则"未知"会先吃掉"未知与假设"。
- 同名段重复出现时**取第一个有内容的**。
- 手工编辑确认书时若照抄了 `to_markdown()` 的 `"(未填)"` 占位文字,那一段仍算缺失。

### `Handoff` {#handoff}

```python
@dataclass
class Handoff:
    doing: str = ""
    decided: str = ""
    deadends: str = ""
    next: str = ""
    scene: str = ""
    step: str = ""
    path: Path | None = field(default=None, compare=False)
```

[换代](glossary.md#换代)时写的[交接书](glossary.md#交接书),五段。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `doing` | `str` | `""` | 在做什么。**必填** |
| `decided` | `str` | `""` | 定了什么 |
| `deadends` | `str` | `""` | 走不通的路 |
| `next` | `str` | `""` | 下一步。**必填** |
| `scene` | `str` | `""` | 现场 |
| `step` | `str` | `""` | 仅用于文书抬头,**不参与解析** |
| `path` | `Path \| None` | `None` | 落盘位置 |

**必填只有 `doing` 和 `next` 两段** —— 硬性要求"走不通的路"非空会逼模型编造。

| 成员 | 签名 | 说明 |
|---|---|---|
| `missing` | `() -> list[str]` | **只检查必填的那两段** |
| `complete` | `() -> bool` | `not missing()` |
| `degraded` | `@property -> bool` | 正文里是否带着降级标记 `[降级:交接没写成]` |
| `parse` | `@classmethod (text: str, *, step: str = "") -> Handoff` | 复用 `Brief` 的分段器 |
| `to_markdown` | `() -> str` | 空段写 `"(空)"` |
| `prompt_block` | `() -> str` | **抬头明确告诉接手者"你在接手"**,防它回头找人要背景 |
| `write` | `(path) -> Path` | 同 `Brief.write` |
| `load` | `@classmethod (path) -> Handoff \| None` | 同 `Brief.load` |

同模块里三个**未导出但语义关键**的成员:`is_overflow(*texts)` 匹配 `prompt is too long`、
`context length exceeded`、`maximum context length`、`too many total text bytes`、
`input length and max_tokens exceed` 等,把"硬错"变成"当场换代";`HANDOFF_PROMPT` 是让
**当前会话自己**写交接的那段提示词(含 `{used}` `{window}` 两个占位符,**不是一个新角色** ——
只有它自己有那段上下文);`degraded(step, prompt, *, why="")` 在交接写不出来时机械拼一份,
`scene` 里塞原始任务的前 **1200** 字符。

### `Goal` {#goal}

```python
@dataclass
class Goal:
    statement: str = ""
    checks: list[str] = field(default_factory=list)
    path: Path | None = None
```

[目标看守](glossary.md#目标看守)里的目标 + 判定清单。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `statement` | `str` | `""` | 目标陈述 |
| `checks` | `list[str]` | `[]` | 判定清单,一条一行 |
| `path` | `Path \| None` | `None` | 落盘位置 |

| 成员 | 签名 | 说明 |
|---|---|---|
| `unverifiable` | `@property -> list[str]` | `checks` 里被标了 `[此环境无法验证:…]` 的条目。**在设目标那一刻就注定判不过** |
| `missing` | `() -> list[str]` | 需要 `statement` 非空**且** `checks` 非空 |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Goal` | `checks` 一条一行,自动去掉 `-` / `*` / `1.` 记号 |
| `to_markdown` | `() -> str` | 清单为空时写 `"(空)"` |
| `prompt_block` | `() -> str` | 喂下游用的紧凑版 |
| `write` / `load` | 同 `Brief` | 落盘与读回 |
| `amend` | `(extra: str) -> Goal` | **追加不覆盖**:`statement` 后拼 `"\n\n(已修改)" + extra`,返回 `self` |

### `Verdict` {#verdict}

```python
@dataclass
class Verdict:
    state: str = ""
    reason: str = ""
    failed: list[str] = field(default_factory=list)
```

[判定者](glossary.md#判定者)一轮判定的结果,**恰好三段**:结论 / 理由 / 未通过。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `state` | `str` | `""` | `"achieved"` / `"not_yet"` / `"unreachable"`,解析不出时是 `""` |
| `reason` | `str` | `""` | 理由 |
| `failed` | `list[str]` | `[]` | 没通过的清单条目 |

| 成员 | 签名 | 说明 |
|---|---|---|
| `achieved` | `@property -> bool` | `state == "achieved"` |
| `unreachable` | `@property -> bool` | `state == "unreachable"` |
| `ok` | `@property -> bool` | 解析出结论没有。**`ok=False` 必须当"未达成"处理,不能当达成** |
| `parse` | `@classmethod (text) -> Verdict` | 见下 |
| `feedback` | `() -> str` | 打回给干活者的话:只给"差在哪",不给方案 |

`parse` 的识别顺序:

1. 先按标题段取「结论」/「判定」。
2. 没有标题段时,整段 strip 后 `fullmatch(r"1|true")` → 达成;`fullmatch(r"0|false")` → 没到。
3. 否则在结论文本里按状态词表(**长词在前**)找第一个命中词。
   **「无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable」全部归到 `unreachable`** ——
   实测栽过:目标平台 macOS、跑在 Linux 容器,判定者看源码分支就判了通过。
4. 仍无 → 找孤立的 `\b1\b` → 达成,`\b0\b` → 没到。
5. 全都不中 → `state=""`、`ok=False`。

`unreachable` 和 `not_yet` **是两个不同的结论**:前者会走"停下来问人"那条路,不是"再来一轮"。

---

## hook 层 {#hook}

源码:[`flower/core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py)

这一层是 flower 的**执行边界**:哪些工具主线程不许碰、超长结果怎么剪、哪个角色去独立 worktree,
全部由 SDK hook 强制,**不靠提示词**。理由很直接 —— 提示词是建议,模型可以不听:已实测即便系统提示
明确写着"不要用 worktree",`isolate_guard` 的注入照样生效(模型传的是 `None`,落地的是 `'worktree'`)。

九个导出:五个返回 `HookMatcher` 的 guard 工厂(`whitelist_guard` 可能返回 `None`)、一个组装器、一个合并器、两个隔离标记函数。
它们不需要手工挂 —— [`Runtime`](#runtime) 会按 `AgentSpec` 自动装配。手工挂只在自己驱动 SDK
(不经过 `Runtime`)时才需要。

**主线程判定统一走一个函数**:`_is_main_thread(data) = not data.get("agent_id")` ——
subagent 的 tool-lifecycle hook 数据里带 `agent_id`,[主线程](glossary.md#主线程)不带。
所有"只拦主线程"的 guard 都靠这一条。

工具组常量(模块级,未导出,但决定了默认 matcher):

```python
HANDS_ON   = "Bash|Write|Edit|NotebookEdit"
WRITE_ONLY = "Write|Edit|NotebookEdit"
BULKY      = "Bash|Read|Grep|Glob|WebFetch|WebSearch"
```

### 速查表:哪个 guard 挂在哪个 SDK 事件上 {#hook-速查表}

| 函数 | SDK hook 事件 | matcher | 拦截对象 | 返回什么 | 谁来装 |
|---|---|---|---|---|---|
| `whitelist_guard` | `PreToolUse` | `Bash\|Write\|Edit\|NotebookEdit` 中**不在 `allowed_tools` 里**的那些 | **仅主线程**调用被禁工具 | `permissionDecision: "deny"` + 理由 | `Runtime._attempt`,**仅当 `spec.delegate_only is False`** |
| `delegate_guard` | `PreToolUse` | `Bash\|Write\|Edit\|NotebookEdit`(`tools=` 可改) | **仅主线程**动手;`allow_glance=True` 时 `is_ephemeral()` 通过的 `Bash` 放行 | `deny` + "去派 subagent" | `workbench_hooks(delegate_only=True)`,**仅当 `Runtime` 有工作台** |
| `isolate_guard` | `PreToolUse` | `Agent` | `tool_input` 既无 `cwd` 也无 `isolation`,且 `subagent_type` 被 `isolated()` 标记过 | `permissionDecision: "allow"` + `updatedInput`(注入 `isolation="worktree"`) | `workbench_hooks`,**仅当 `agents` 里有被标记的角色** |
| `index_guard` | `PostToolUse` | `Write\|Edit` | `tool_input.file_path` 落在 `workbench.root` 内 | `{}`(副作用是 `workbench.refresh()`) | `workbench_hooks`,总是装 |
| `spill_guard` | `PostToolUse` | `Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch` | `tool_response` 里 ≥ `threshold` 字符的**字符串字段**;读 spill 目录本身放行 | `updatedToolOutput`(落盘 + 一行指针 + 开头 400 字符) | `workbench_hooks`,**仅当 `spill_threshold` 为真** |

**从这张表能读出的关键推论**:`Runtime(workbench=False)` 时 `workbench_hooks` 整个不装;
而对 `delegate_only=True` 的协调者,`whitelist_guard` 也被跳过 —— **主线程一道墙都没有**。
详见 [Runtime](#runtime) 那条警告。

### `whitelist_guard()` {#whitelist-guard}

```python
def whitelist_guard(allowed: list[str] | None, *, role: str = "这个角色") -> HookMatcher | None
```

**让 `allowed_tools` 对动手的那四个工具真正排他。**

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `allowed` | `list[str] \| None` | 必填,位置参数 | 通常直接传 `spec.allowed_tools` |
| `role` | `str` | `"这个角色"` | 拒绝文案里的自称。`Runtime` 传的是 `spec.name` |

- **挂在 `PreToolUse`**,matcher 是 `"|".join(banned)`,`banned` = `Bash` `Write` `Edit` `NotebookEdit`
  中不在 `allowed` 里的那些。
- 命中即 `permissionDecision: "deny"`,文案大意:"XX 没有 YY。**这是有意的,不是配置漏了。**
  把结论写进你的回话正文里,框架会从那里取 —— 不要试别的写法绕过去。"
- **只拦本会话主线程**,subagent 放行 —— subagent 的工具由 `AgentDefinition.tools` 决定。
- 没有需要拦的工具时返回 **`None`**(比如 `worker()` 那种全套工具的角色),调用方据此决定装不装。

**它为什么必须存在**:`allowed_tools` 是**免审批清单,不是排他白名单**。实测三处证据 ——
确认者用了不在白名单里的 `WebFetch`;设目标的判定者跑了 11 次 `Bash`;$0.1 的探针里
`allowed_tools=["Read"]` 的 agent 照样调得动 `Write`/`Bash`。
所以 `clarify()` / `judge()` 的"没有写工具"**靠的是这道 hook**,不是白名单本身。

好处是它从 `allowed_tools` 派生,所以 `judge(can_run=True)` 自动保留 `Bash`、仍然拦
`Write`/`Edit` —— 不需要额外的开关。

### `delegate_guard()` {#delegate-guard}

```python
def delegate_guard(*, tools: str = HANDS_ON, allow_glance: bool = False) -> HookMatcher
```

**主线程自己动手 → 拒绝,并指路。**

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `tools` | `str` | `"Bash\|Write\|Edit\|NotebookEdit"` | matcher。是正则串,不是列表 |
| `allow_glance` | `bool` | `False` | `True` 时 `tool_name == "Bash"` 且 [`is_ephemeral(command)`](#is-ephemeral) 为真就放行 |

- **挂在 `PreToolUse`**,matcher 就是 `tools`。
- 主线程调这四个工具 → deny,理由里**给出下一步怎么做**:用 `Agent` 工具派一个 subagent 去做,
  任务里写清目标与验收标准,并要求它把长产出写进 `.flower/artifacts/`、回话只给路径与结论。
- subagent 一律放行。

和 `whitelist_guard` 的区别是**措辞**:两者拦同一批工具,但这一道说的是"去派人",更对路。
所以 `delegate_only=True` 的角色只装这一道,重复装会让模型收到两条矛盾指引。

`allow_glance=True` 的放行判据和"结果会不会被剪掉"是**同一个函数**([`is_ephemeral`](#is-ephemeral))——
放行集合必须等于过期集合,改一边就必须改另一边。

### `spill_guard()` {#spill-guard}

```python
def spill_guard(
    workbench: Workbench,
    *,
    threshold: int = 4000,
    tools: str = BULKY,
    main_only: bool = False,
) -> HookMatcher
```

超过阈值的工具结果**当场[落盘](glossary.md#落盘)**,上下文里只留一行指针 —— 不是等上下文满了
再回头压缩。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `workbench` | `Workbench` | 必填,位置参数 | 落盘目录是 `<workbench.root>/spill/` |
| `threshold` | `int` | `4000` | 超过多少字符才落盘 |
| `tools` | `str` | `"Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch"` | matcher |
| `main_only` | `bool` | `False` | `False`(默认)= subagent 的结果也落盘 |

- **挂在 `PostToolUse`**,返回
  `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": <剪过的>}}`。
- 落盘文件名是内容的 `sha256` 前 16 位 + `.txt`,上下文里换成一行指针 + **开头 400 字符**。
- `updatedToolOutput` **必须保持原工具的输出结构**,所以只替换 dict 里过长的**字符串字段**;
  **list 一律不碰**(里面可能是图片块)。结构不对会被拒(原文照旧,不报错)。
- **读落盘文件本身时必须放行** —— 否则"用 `Read` 读它"是句空话:读回来的全文又被落盘,无限循环。
  实测撞到过,模型连试五种写法绕。

### `index_guard()` {#index-guard}

```python
def index_guard(workbench: Workbench) -> HookMatcher
```

往[工作台](glossary.md#工作台)写了东西就刷新 `INDEX.md`,下一个 agent 开局就知道它存在。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `workbench` | `Workbench` | 必填,位置参数 | 判定范围和刷新对象 |

**挂在 `PostToolUse`**,matcher `"Write|Edit"`。`tool_input["file_path"]` resolve 后落在
`workbench.root` 内就调 `workbench.refresh()`。**永远返回 `{}`** —— 它不改任何东西,只有副作用。

### `isolate_guard()` {#isolate-guard}

```python
def isolate_guard(agents: dict[str, AgentDefinition], *, on_inject: Any = None) -> HookMatcher
```

按角色给 subagent 分配独立 git worktree,实现[隔离](glossary.md#隔离)。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `agents` | `dict[str, AgentDefinition]` | 必填,位置参数 | 角色表,用来查 `subagent_type` 有没有被标记 |
| `on_inject` | `Any` | `None` | 可选回调,按 `on_inject(subagent_type, description)` 调用 |

**挂在 `PreToolUse`**,matcher `"Agent"`。三个条件同时成立才注入:`tool_name == "Agent"`、
`tool_input` **既没有 `cwd` 也没有 `isolation`**、`subagent_type` 对应的角色被 `isolated()` 标记过。
成立就返回 `permissionDecision: "allow"` + `updatedInput`(把 `isolation` 设成 `"worktree"`)。

`isolation` 与 `cwd` 在 `Agent` 工具里**互斥** —— 模型自己指定了 `cwd` 就尊重它。
"要不要隔离"是**角色的属性**,不是全局开关,也不是每次派活都判断;不需要隔离的角色一个字节都不会被加上。

**开隔离就要把[工作台](glossary.md#工作台)挪出仓库。** 被隔离的 agent 写不进共享 checkout,
所以工作台必须用 `home=` 指到仓库外。`starter_flow(isolate=True)` 用
`<ws>.parent/.flower-<ws.name>`,`Runtime(workbench=True)` 用 `<run_dir>/workbench` ——
两个都在仓库外,**但不是同一个目录**,别混着用。

### `isolated()` / `wants_isolation()` {#isolated}

```python
def isolated(agent: AgentDefinition, flag: bool = True) -> AgentDefinition
def wants_isolation(agent: AgentDefinition | None) -> bool
```

给一个 subagent 定义打上"需要独立工作区"的标记,以及读回这个标记。

| 函数 | 参数 | 默认 | 说明 |
|---|---|---|---|
| `isolated` | `agent: AgentDefinition` | 必填 | 要打标记的定义。**返回的是同一个对象** |
| | `flag: bool` | `True` | 位置参数。`False` = 摘掉标记 |
| `wants_isolation` | `agent: AgentDefinition \| None` | 必填 | `None` 也接受,返回 `False` |

标记走 `object.__setattr__` 打的 Python 侧属性 `_flower_isolate`,**不是 dataclass 字段** ——
SDK 用 `asdict()` 序列化,只认已声明字段,所以这个标记不会漏到 CLI 那边(已实测)。

**代价**:对 `AgentDefinition` 做 `dataclasses.replace()` 会丢掉这个标记,隔离静默失效。

`worker(isolate=True)` 内部就是走 `isolated()`。

### `workbench_hooks()` {#workbench-hooks}

```python
def workbench_hooks(
    workbench: Workbench,
    *,
    delegate_only: bool = True,
    spill_threshold: int | None = 4000,
    agents: dict[str, AgentDefinition] | None = None,
    allow_glance: bool = False,
) -> dict[str, list[HookMatcher]]
```

一次装好工作台需要的那几个 hook。`Runtime._attempt` 调的就是它。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `workbench` | `Workbench` | 必填,位置参数 | 传给 `index_guard` 和 `spill_guard` |
| `delegate_only` | `bool` | `True` | `True` 才装 `delegate_guard` |
| `spill_threshold` | `int \| None` | `4000` | 为真才装 `spill_guard` |
| `agents` | `dict[str, AgentDefinition] \| None` | `None` | 里面**有任何一个**被 `isolated()` 标记才追加 `isolate_guard` |
| `allow_glance` | `bool` | `False` | 透传给 `delegate_guard(allow_glance=)` |

产出:

- `PreToolUse`:`delegate_only=True` → `[delegate_guard(allow_glance=allow_glance)]`;
  有被标记的角色 → 追加 `isolate_guard(agents)`。
- `PostToolUse`:总是 `[index_guard(workbench)]`;`spill_threshold` 为真 → 追加
  `spill_guard(workbench, threshold=spill_threshold)`。
- **空列表的事件键会被剔掉**,不返回空 list。

### `merge_hooks()` {#merge-hooks}

```python
def merge_hooks(*groups: dict[str, list[Any]] | None) -> dict[str, list[Any]]
```

按事件名把多组 hook 配置**拼接**。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `*groups` | `dict[str, list[Any]] \| None` | 变长参数 | 任意多组。`None` 组跳过 |

用 `extend`,**不去重** —— 同一个 guard 传两次就会装两次。`Runtime` 用它把 `spec.hooks`、
`workbench_hooks(...)` 和 `whitelist_guard` 合到一起。

---

## 工作台 {#工作台}

源码:[`flower/core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py)

### `Workbench` {#workbench}

```python
@dataclass
class Workbench:
    workspace: Path
    dirname: str = ".flower"
    max_index_entries: int = 40
    home: Path | None = None
```

落盘的工作目录,三个子目录 + 一份索引。索引**注入到 system prompt**,所以 agent 每轮都知道
手上有什么。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `workspace` | `Path` | 必填,位置参数 | 工作区。`__post_init__` 会 resolve |
| `dirname` | `str` | `".flower"` | 工作台目录名,相对 `workspace` |
| `max_index_entries` | `int` | `40` | **只管 `prompt_block()`**:注入 system prompt 的那段里每类最多列几条,超出的收成一行"…另有 N 个"。`INDEX.md` 本身不受限,列全部 |
| `home` | `Path \| None` | `None` | 给了就用它当 `root`,**忽略 `dirname`**。非 `None` 时也会 resolve |

| 成员 | 签名 | 说明 |
|---|---|---|
| `root` | `@property -> Path` | `home` 给了就用它,否则 `workspace / dirname` |
| `external` | `@property -> bool` | `root` 是否在 `workspace` **之外**。隔离模式下应为 `True` |
| `scripts` | `@property -> Path` | `root / "scripts"`,要跑第二次的脚本 |
| `artifacts` | `@property -> Path` | `root / "artifacts"`,超过 2000 字符的长产出 |
| `notes` | `@property -> Path` | `root / "notes"`,关键决策,一个决策一个文件 |
| `index_path` | `@property -> Path` | `root / "INDEX.md"` |
| `show` | `(p: Path) -> str` | 给模型看的路径:工作区内用相对路径,外面用绝对路径 |
| `ensure` | `() -> Workbench` | mkdir 三个目录,返回 `self`(可链式:`Workbench(ws).ensure()`) |
| `scan` | `(d: Path) -> list[tuple[str, str, int]]` | `(展示路径, 描述, 字节数)`。递归 `rglob("*")`,跳过 `.` 开头的文件 |
| `refresh` | `() -> str` | 重写 `INDEX.md` 并返回内容 |
| `prompt_block` | `() -> str` | **注入 system prompt 的那一段**。有意做短 —— 它每轮都在 |

脚本自述格式:首 8 行内的 `# desc: 一句话`(也认 `//` 和 `--` 注释符),
退化到第一行非空注释或 docstring 首行(截 100 字)。

`prompt_block()` 注入的三条规矩:

1. 要跑第二次的脚本写进 `scripts/`,首行 `# desc:`。
2. 超过 **2000 字符**的产出写进 `artifacts/`,对话里只给路径和结论。
3. 关键决策写进 `notes/`,一个决策一个文件。

`external=True` 时 `prompt_block()` 会额外插一句"用绝对路径访问它"。

**索引 subagent 继承不到。** 它走的是会话级的 `system_prompt.append`,而 subagent 有自己的
system prompt(实测 $0.2461)。所以"长产出写 `artifacts/`、工作台在哪"这两条必须由
[协调者](glossary.md#协调者)在[任务书](glossary.md#任务书)里转述 —— **那是唯一通道**,不是冗余。
`WORKER_RULES` 里**故意没写**这条:真实路径由 `Workbench` 生成,写死会错。

---

## 会话存储 {#会话存储}

源码:[`sqlite.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/sqlite.py) ·
[`trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py) ·
[`prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py)

三层继承:`SqliteSessionStore` ← `TrimmingSessionStore` ← `PruningSessionStore`。
`Runtime` **永远用最外层**,三层的策略由构造参数控制。

三层各管一件事:落盘、按体积和价值[裁剪](glossary.md#裁剪)、按"是不是错误"[剪除](glossary.md#剪除)。
裁剪和剪除都发生在 **`load()`**(即 resume 把历史喂回模型)那一刻,SQLite 里的原始记录一个字节不动。

### `SqliteSessionStore` {#sqlitesessionstore}

```python
class SqliteSessionStore(SessionStore):
    def __init__(self, path: str | Path) -> None
```

实现 SDK 的 `SessionStore` 协议,三张表 `entries` / `meta` / `summaries`。
store key 是 `project_key/session_id[/subpath]` —— **子 agent 的 transcript 用 subpath 区分**。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `path` | `str \| Path` | 必填,位置参数 | 数据库文件。连接用 `check_same_thread=False` |

| 方法 | 签名 | 说明 |
|---|---|---|
| `append` | `async (key, entries) -> None` | 按 uuid 幂等去重(先去已落库的,再去批次内重复的)。整批重放时**不推进 mtime、不重复 fold summary**;只有主 transcript(`subpath is None`)参与 summary |
| `projects` | `() -> list[str]` | 库里实际存在的 `project_key`。**SDK 由 cwd 推导它,查询前用这个确认,别猜** |
| `has_session` | `(project_key: str, session_id: str) -> bool` | **同步的,不读 payload**,只查 meta 一行。给"同一路径接续"用 —— resume 一个不存在的会话要等子进程起来才炸 |
| `last_context` | `(project_key: str, session_id: str, *, scan: int = 60) -> int` | 最后一轮模型实际看到多大上下文,查不到返回 `0`。只倒着扫最后 `scan` 条;`input + cache_read + cache_creation` 三项都算(只看 `input_tokens` 会严重低估) |
| `load` | `async (key) -> list[SessionStoreEntry] \| None` | 按 seq 排序;无行返回 `None` |
| `list_sessions` | `async (project_key) -> list[SessionStoreListEntry]` | 只要主 transcript |
| `list_session_summaries` | `async (project_key) -> list[SessionSummaryEntry]` | 列出会话摘要 |
| `delete` | `async (key) -> None` | 删主 transcript 时**级联删掉子 agent 的**,避免孤儿 |
| `list_subkeys` | `async (key) -> list[str]` | 列出这条会话下的子 transcript |
| `close` | `() -> None` | 关连接 |

内部的 `_next_mtime` 保证**严格单调** —— `list_sessions` 和 summary sidecar 共用这个时钟,
否则 SDK 的 staleness 快路径会误判。

### `TrimPolicy` {#trimpolicy}

```python
@dataclass
class TrimPolicy:
    keep_recent: int = 20
    min_chars: int = 2000
    spill_dirname: str = ".flower/spill"
    enabled: bool = True
```

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `keep_recent` | `int` | `20` | 最近 N 个 `tool_result` 保留原文 |
| `min_chars` | `int` | `2000` | 短结果不值得裁 |
| `spill_dirname` | `str` | `".flower/spill"` | **相对 `workspace`,必须在工作区内** —— 否则 agent 的 `Read` 够不到 |
| `enabled` | `bool` | `True` | `Runtime(trim=False)` 时这里是 `False` |

| 方法 | 签名 | 说明 |
|---|---|---|
| `placeholder` | `(path: str, n: int) -> str` | 生成替换正文的那行指针 |

**两个 spill 目录不是同一个。** `spill_guard` 落在 `<workbench.root>/spill/`(可以在工作区外);
`TrimPolicy.spill_dirname` 落在 `<workspace>/.flower/spill/`(**必须在工作区内**)。
两者分别对应"当场剪"和"resume 时剪",目录不同是有意的,别改成一个。

### `EphemeralPolicy` {#ephemeralpolicy}

```python
@dataclass
class EphemeralPolicy:
    enabled: bool = True
    keep_recent: int = 6
    max_chars: int = 2000
    text: str = "[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"
```

[一次性命令](glossary.md#一次性命令)的结果过期策略。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `enabled` | `bool` | `True` | 关掉则过期标记整个不做 |
| `keep_recent` | `int` | `6` | 最近 N 个豁免。**比 `TrimPolicy` 的 20 小得多** |
| `max_chars` | `int` | `2000` | 超过就跳过,交给 `TrimPolicy` 归档 |
| `text` | `str` | 见签名 | 替换文案,`{cmd}` 和 `{age}` 两个占位符 |

| 方法 | 签名 | 说明 |
|---|---|---|
| `placeholder` | `(cmd: str, age: int) -> str` | 套 `text` 生成替换正文 |

**只作用于 `Bash` 工具的结果**,且命令要匹配一次性命令白名单。**`Read` 不在此列** ——
文件内容不会因时间流逝而失真到误导的程度。过期内容**不落盘**,直接扔。

### `is_ephemeral()` {#is-ephemeral}

```python
def is_ephemeral(cmd: str) -> bool
```

判一条 Bash 命令是不是[一次性命令](glossary.md#一次性命令)。
**`delegate_guard` 的放行判断和剪枝的过期判断共用这一个函数** —— 主 agent 能自己跑的命令集合
必须等于结果会被标记过期的集合。放行不剪枝,过期的 `git status` 会永久占上下文还会误导;
剪枝不放行,主 agent 为一条 `ls` 派个 subagent,4.3k 启动成本换几十字符。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `cmd` | `str` | 必填,位置参数 | 完整命令行 |

判定顺序:

1. 空 / 全空白 → `False`。
2. 命令替换(`$(`、反引号、`<(`、`>(`)或"会改状态"的写法命中 → `False`。
3. 摘掉安全重定向(`2>&1`、`&> /dev/null` 之类)后仍含 `>` 或 `<` → `False`。
4. 摘掉 `&&` / `||` / `;` / `|` 后仍剩单个 `&`(后台执行)→ `False`。
5. 按 `&&` / `||` / `;` / `|` 拆开,**每一段都必须命中白名单**。

白名单动词大类:只读的 `git` 子命令(`status` `diff` `log` `show` `branch` `rev-parse` 等)、
目录与系统信息(`ls` `pwd` `df` `du` `date` `whoami` `env` 等)、进程与容器
(`ps` `top` `lsof` `docker ps` `kubectl get` 等)、看文件(`cat` `head` `tail` `wc` `stat` `find` `tree`)、
查路径(`which` `whereis` `command -v` `type`)、文本处理(`grep` `rg` `sort` `uniq` `awk` `sed` `jq` `diff` 等)。

即使动词在白名单,这些写法也会被拦:`xargs`、`exec`、`eval`、`source`、`tee`、
`find -delete` / `-ok` / `-fprint`、`sed -i`、`sort -o`、`awk` 里的 `system(` 和 `print >`、
`git branch -D/-d/-m`、`git * --force/--hard/--prune`。

第一版一刀切拒绝所有复合命令,**实测让 glance 完全失效**(协调者三次尝试全被拦),
所以改成了逐段判。

### `TrimmingSessionStore` {#trimmingsessionstore}

```python
class TrimmingSessionStore(SqliteSessionStore):
    def __init__(
        self,
        path: str | Path,
        workspace: str | Path,
        policy: TrimPolicy | None = None,
        ephemeral: EphemeralPolicy | None = None,
    ) -> None
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `path` | `str \| Path` | 必填 | 数据库文件 |
| `workspace` | `str \| Path` | 必填 | 落盘目录的基准 |
| `policy` | `TrimPolicy \| None` | `None` | 不给就用默认 `TrimPolicy()` |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | 不给就用默认 `EphemeralPolicy()` |

公开属性:`workspace`、`policy`、`ephemeral`、`last_report: dict[str, int]`。

`load()` 的顺序:`super().load()` → 清空 `last_report` → `ephemeral.enabled` 则 `expire()` →
`policy.enabled` 则 `trim()`。**`enabled=False` 时该步整个跳过。**

| 方法 | 说明 |
|---|---|
| `expire(entries)` | 把过期的时效性 `Bash` 结果**只换正文,块保留**。命令从上一条 assistant 消息的 `tool_use` 里找;跳过 `isCompactSummary` / `isMeta`;超过 `max_chars` 的跳过(交给 `trim`);最后 `keep_recent` 个豁免。写 `last_report["expired"]` |
| `trim(entries)` | `>= min_chars` 的 `tool_result` 正文落盘到 `<workspace>/<spill_dirname>/<sha256前16位>.txt`,块内容换成指针;最后 `keep_recent` 个豁免。写 `last_report` 的 `cleared` / `kept` / `chars_saved` |

**只裁纯文本**:遇到 `image` / `document` 块原样留着。

**两条结构性红线**:`tool_result` **块本身必须在**,只能换 content(少一个就是
"Missing Tool Result Block");`isCompactSummary` 条目不能动。

### `trim_report()` {#trim-report}

```python
def trim_report(store: TrimmingSessionStore) -> str
```

把 `store.last_report` 渲染成一行中文,给 UI 打日志用。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `store` | `TrimmingSessionStore` | 必填,位置参数 | 也接受子类 `PruningSessionStore` |

三种输出:没动作 → `"未裁剪"`;只有过期 → `"N 个时效性结果标记为过期"`;
否则 `"裁掉 N 个工具结果(保留最近 M 个),省下 ~X tokens"`,其中 X = `chars_saved // 4`。

### `PrunePolicy` {#prunepolicy}

```python
@dataclass
class PrunePolicy:
    drop_api_errors: bool = True
    neutralize_interrupts: bool = True
    interrupt_text: str = "[上一轮在此处被中断,该工具结果未产生]"
    keep_denials: int = 1
```

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | 摘掉合成 API 错误消息(断线残渣) |
| `neutralize_interrupts` | `bool` | `True` | 中断残留的 `tool_result` 换成中性说明 |
| `interrupt_text` | `str` | 见签名 | 中性说明的文案 |
| `keep_denials` | `int` | `1` | 保留最近 N 次被拒的工具调用 |

`keep_denials` 的理由:被拒调用从没执行过,结果里没信息,但占位不小(实测一次 273 字符 =
93 字拒绝语 + 180 字**死命令原文**)。更要紧的是**它会误导** —— 实测协调者读到几条
"不直接使用 Bash"之后,连放行的 `git status` 都不再尝试,学成了习得性无助。
**默认留 1 条而不是 0**:最新那次拒绝能防止模型在同一轮里反复重试同一条被拦命令。

### `PruningSessionStore` {#pruningsessionstore}

```python
class PruningSessionStore(TrimmingSessionStore):
    def __init__(
        self,
        path: str | Path,
        workspace: str | Path,
        policy: TrimPolicy | None = None,
        prune: PrunePolicy | None = None,
        ephemeral: EphemeralPolicy | None = None,
    ) -> None
```

**`Runtime` 的默认 store。**

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `path` | `str \| Path` | 必填 | 数据库文件 |
| `workspace` | `str \| Path` | 必填 | 落盘目录的基准 |
| `policy` | `TrimPolicy \| None` | `None` | 裁剪策略 |
| `prune` | `PrunePolicy \| None` | `None` | 剪除策略 |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | 过期策略 |

公开属性在父类之外多三个:`prune_policy`、`pruned`、`denials_dropped`。

`load()` = `super().load()`(先 `expire` + `trim`)→ `self.prune(entries)`。`prune` 做三件事:

1. **摘掉过早的被拒调用**:靠 harness 的结构性标记 `toolDenialKind == "permission-rule"` 判定
   (比匹配拒绝语文案可靠),保留最后 `keep_denials` 个,其余的 `tool_use` **和** `tool_result`
   块一起摘掉。同一条 assistant 消息里有多个 `tool_use` 时**只摘中标的**,否则会变成
   "Missing Tool Result Block";文本和 thinking 块保留。
2. **摘掉合成 API 错误消息。** SQLite 里原样保留,只是不喂回去。
3. **中断残留的 `tool_result` 换成中性说明** —— 只换正文,不摘条目。

**唯一的结构性红线**:transcript 是 `parentUuid` 单链,摘掉一条就必须把它的孩子接到最近的存活祖先。
内部的 `relink` 的 `entries` **必须是完整列表(含要摘的那些)**,过滤由它自己做 ——
调用方先剔掉再传进来的话链会断在那儿,前面的历史全丢(**已踩过:被摘条目在末尾时不暴露,
在中间就炸**)。

**参数顺序和父类不同**:父类是 `(path, workspace, policy, ephemeral)`,子类是
`(path, workspace, policy, prune, ephemeral)` —— **第四个位置参数从 `ephemeral` 变成了 `prune`**,
按位置传会静默错位。一律用关键字传。

---

## 韧性 {#韧性}

源码:[`flower/core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py)

断网时挂着等而不是失败退出。四个导出:一个策略 dataclass + 三个可以单独用的探测函数。

### `Resilience` {#resilience}

```python
@dataclass
class Resilience:
    enabled: bool = True
    max_attempts: int = 6
    base_delay: float = 4.0
    max_delay: float = 120.0
    probe_timeout: float = 5.0
    probe_interval: float = 15.0
    max_offline_wait: float = 3600.0
    retry_unknown: bool = True
    resume_prompt: str = "上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,从中断处接着做,不要重头来过。"
```

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `enabled` | `bool` | `True` | 关掉则任何故障都不重试 |
| `max_attempts` | `int` | `6` | **含首次** |
| `base_delay` | `float` | `4.0` | 退避基数,秒 |
| `max_delay` | `float` | `120.0` | 退避上限,秒 |
| `probe_timeout` | `float` | `5.0` | 单次探针超时 |
| `probe_interval` | `float` | `15.0` | 两次探针之间等多久 |
| `max_offline_wait` | `float` | `3600.0` | 最多挂着等多久,默认 1 小时 |
| `retry_unknown` | `bool` | `True` | 分不出类的错误要不要重试 |
| `resume_prompt` | `str` | 见签名 | 续跑时说的话。**有意不含任何错误细节** —— 模型需要知道"被打断了、接着做",不需要知道是 `ENOTFOUND` 还是 503 |

| 方法 | 签名 | 说明 |
|---|---|---|
| `delay_for` | `(attempt: int) -> float` | `min(base_delay * 2**(attempt-1), max_delay)` 再乘 `0.75 + random()*0.5`(±25% 抖动) |
| `should_retry` | `(kind: str) -> bool` | `kind == "transient"`,或 `kind == "unknown"` 且 `retry_unknown` |
| `wait_online` | `async (notify=None) -> bool` | 挂着等网络回来。回来返回 `True`,超 `max_offline_wait` 返回 `False`。`notify` 是 `(str) -> None` 回调,**第一次不可达时**和**恢复时**各发一次 |

### `classify()` {#classify}

```python
def classify(text: str | None) -> str
```

把错误文本分成 `"transient"` / `"fatal"` / `"unknown"` 三类。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `text` | `str \| None` | 必填,位置参数 | 错误消息原文。为空返回 `"unknown"` |

**先判 fatal 再判 transient** —— 401 之类的文本常带 `connection` 字样,顺序反了会死等。

| 类 | 命中什么 |
|---|---|
| `fatal` | `400` `401` `403` `404`、`invalid api key`、`authentication`、`unauthorized`、`permission denied`、`invalid_request`、`credit balance`、`quota exceeded`、`budget`、`max_turns`、`CLINotFound` |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`、`socket hang up`、`fetch failed`、`network error`、`Connection error`、`Can't reach the API server`、`429` `500` `502` `503` `504` `529`、`overloaded`、`rate limit`、`too many requests`、`timeout` / `timed out`、`temporarily unavailable`、`service unavailable`、`internal server error` |

### `endpoint()` {#endpoint}

```python
def endpoint() -> tuple[str, int]
```

要探的主机和端口,跟着 `ANTHROPIC_BASE_URL` 走,默认 `https://api.anthropic.com`;
端口默认 `80`(http)或 `443`。

**探自建网关时必须探它** —— `api.anthropic.com` 通说明不了网关通。

### `reachable()` {#reachable}

```python
async def reachable(host: str, port: int, timeout: float = 5.0) -> bool
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `host` | `str` | 必填,位置参数 | 主机名 |
| `port` | `int` | 必填,位置参数 | 端口 |
| `timeout` | `float` | `5.0` | 秒 |

**只做 DNS(`getaddrinfo`)+ TCP 握手**,不发 HTTP、不带凭证、**不花钱**。任何异常都算不可达。

---

## 事件与交互 {#事件与交互}

源码:[`events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py) ·
[`human.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/human.py)

[事件](glossary.md#事件)是 SDK 消息流被压平成的稳定结构。**[交互层](glossary.md#交互层)只认
`Event`,不 import 任何 SDK 类型** —— 这是换 UI 不用改核心的边界。见[换交互层](../guide/interaction.md)。

### `Event` {#event}

```python
@dataclass
class Event:
    kind: EventKind
    text: str = ""
    tool: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None

    def __str__(self) -> str: ...
```

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `kind` | `EventKind` | 必填 | 见下表 |
| `text` | `str` | `""` | 正文 |
| `tool` | `str` | `""` | 工具名,仅 `tool_call` 有 |
| `payload` | `dict[str, Any]` | `{}` | 结构化附加信息 |
| `raw` | `Any` | `None` | 原始 SDK 对象,想深挖时用 |

`__str__`:`tool_call` 时是 `f"[{tool}] {text}"`,否则是 `text`,`text` 为空则 `f"<{kind}>"`。
所以 `print(ev)` 直接可读。

`EventKind` 一共 **15** 个:

| kind | 谁发 | 说明 |
|---|---|---|
| `text` | `normalize` | assistant 正文 |
| `thinking` | `normalize` | 思考块 |
| `tool_call` | `normalize` | 工具调用。`text` 是 `file_path` / `command` / `pattern` 摘要,截 200 字 |
| `tool_result` | `normalize` | 工具结果。`text` 截 500 字,payload 带 `tool_use_id` / `is_error` |
| `task` | `normalize` | 三种 Task 消息,`text` 是消息类名 |
| `system` | `normalize` | 其余系统消息,`text` 是 subtype |
| `reset` | `normalize` | `compact_boundary` / `microcompact_boundary` / `ConversationResetMessage` |
| `result` | `normalize` | `ResultMessage`,payload 带 `session_id` / `cost_usd` / `num_turns` / `is_error` |
| `error` | `normalize` | 合成 API 错误消息,payload 带 `{"synthetic": True}` |
| `prompt` | `normalize` | `UserMessage`。**正文是输入,不是模型产出**,所以不进 `StepResult.text` |
| `unknown` | `normalize` | 认不出来的 |
| `retry` | `Runtime` | 重试通知 |
| `step` | `Workflow.run` | payload:`{"index", "total", "resumed", "woke"}` |
| `handoff` | `Runtime` | payload 里 `phase` ∈ `{"near", "writing", "done"}` |
| `ask` | `HumanChannel` | 提问,**也承载"人主动说的话"** |

**最后四个不由 `normalize()` 产生。**

所有 assistant / user 事件的 `payload` 里都带:

| 键 | 类型 | 说明 |
|---|---|---|
| `subagent` | `bool` | `bool(parent_tool_use_id)` |
| `parent_tool_use_id` | `str` | 仅 `subagent` 为真时有 |
| `context` | `int` | `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`。**这是[换代](glossary.md#换代)判据的唯一来源**,也是长程运行最该被看见的数字 |

**`ask` 这个 kind 同时承载"提问"和"人主动说的话"。** 后者的 `payload["kind"] == "mail"`,
**没有 `options` / `remaining`**。UI 必须先判 `payload.get("kind")` 再决定怎么渲染,
否则会把一句话当成一个待回答的提问挂住。

### `normalize()` {#normalize}

```python
def normalize(message: Any) -> list[Event]
```

把一条 SDK 消息压平成 0 到 N 个 `Event`。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `message` | `Any` | 必填,位置参数 | 任意 SDK 消息对象 |

关键分支:

- **合成 API 错误消息**(`isApiErrorMessage=True` 或 `model == "<synthetic>"`)→ 单个
  `Event("error", payload={"synthetic": True})`。**这一条是有意的** —— 否则断线文案会被当成正文
  进 `StepResult.text`,再传给下一步。
- `AssistantMessage` → `kind="text"`;`UserMessage` → `kind="prompt"`。
- `ToolUseBlock` → `Event("tool_call", text=<摘要>, tool=block.name, payload={"id", "input"})`。
- `ToolResultBlock` → `Event("tool_result", text=content[:500], payload={"tool_use_id", "is_error"})`。
- `ResultMessage` → `Event("result", text=subtype, payload={"session_id", "cost_usd", "num_turns", "is_error"})`。
- `compact_boundary` / `microcompact_boundary` → `Event("reset", payload={"trigger", "pre_tokens", "post_tokens", "micro", "subtype"})`。

### `Ask` {#ask}

```python
@dataclass
class Ask:
    id: str
    question: str
    options: list[str] = field(default_factory=list)
    asked_at: float = field(default_factory=time.time)
    state: str = "asked"
    answer: str = ""
```

一次向人的提问。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `id` | `str` | 必填 | 回答时用它定位 |
| `question` | `str` | 必填 | 问题正文 |
| `options` | `list[str]` | `[]` | 备选项。人也可以不选、自己打字 |
| `asked_at` | `float` | `time.time()` | 提问时刻 |
| `state` | `str` | `"asked"` | `asked` → `answered` / `timeout` / `declined` / `over_budget` / `invalid` |
| `answer` | `str` | `""` | 回答正文 |

| 成员 | 签名 | 说明 |
|---|---|---|
| `waited_s` | `@property -> float` | 已经等了多久 |
| `event` | `(remaining: int = 0) -> Event` | 产出 `Event("ask", text=question, payload={"id", "options", "state", "answer", "remaining", "asked_at"}, raw=self)` |

### `HumanChannel` {#humanchannel}

```python
HumanChannel(
    *,
    on_event: Callable[[Event], None] | None = None,
    max_asks: int | None = None,
    timeout_s: float | None = 1800.0,
    log_path: str | Path | None = None,
    amend_path: str | Path | None = None,
    over_budget_text: str = OVER_BUDGET,
    timeout_text: str = TIMEOUT,
    declined_text: str = DECLINED,
)
```

一个**进程内 MCP server**(两个工具)+ 一组给 UI 用的方法。模型侧只看到
`mcp__human__ask` 和 `mcp__human__inbox`。构造参数全部 keyword-only。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `on_event` | `Callable[[Event], None] \| None` | `None` | **推**模式的出口。给了它,`Workflow.run` 就不会再接线 |
| `max_asks` | `int \| None` | `None` | **不限次数**。给数字就是硬额度,`0` = 不许提问(全自动 / CI)。超额时工具**直接回绝,不阻塞** |
| `timeout_s` | `float \| None` | `1800.0` | 30 分钟。`None` = 永远等;**`<= 0` = 不等,所有提问立刻落空** |
| `log_path` | `str \| Path \| None` | `None` | 问答**追加**到磁盘,不占上下文 |
| `amend_path` | `str \| Path \| None` | `None` | 人在运行途中说的话追加到这个文件(通常就是需求确认书)。**不落盘就活不过步骤边界** —— 下一步是新会话,只读冻结件 |
| `over_budget_text` | `str` | 模块常量 | 超额时回给模型的话 |
| `timeout_text` | `str` | 模块常量 | 超时时回给模型的话 |
| `declined_text` | `str` | 模块常量 | 被跳过时回给模型的话 |

公开属性:构造参数同名的八个,外加 `asks: list[Ask]`、`mail: list[Mail]`、
`ui_errors: list[str]`(**UI 回调抛的异常收在这里,不中断运行**)。

| 成员 | 签名 | 说明 |
|---|---|---|
| `tool_name` | `@property -> str` | `"mcp__human__ask"` |
| `inbox_name` | `@property -> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict[str, Any]` | 直接塞给 `AgentSpec.mcp_servers`。**键名必须与 server 名一致**,所以由它一起给出 |
| `ask` | `async (question: str, options: list[str] \| None = None) -> Ask` | 挂住等人。**除 `CancelledError` 外永不抛异常** —— 没人应答也是一种答案,用 `ask.state` 区分 |
| `send` | `(text: str) -> Mail \| None` | 人主动说一句话。**任何线程可调**。不打断 agent;内部会自动调 `amend()` |
| `amend` | `(text: str, *, label: str = "运行中补充") -> bool` | 追加进 `amend_path`。返回是否真写了(没配路径、空文本、`OSError` 都是 `False`) |
| `pending_mail` | `() -> list[Mail]` | 未被取走的 mail |
| `remaining` | `@property -> int` | 还能问几次。**`max_asks=None` 时返回 `-1`**,不是 0 也不是无穷 |
| `pending` | `() -> list[Ask]` | 当前挂着等答的提问 |
| `next_ask` | `async (timeout: float \| None = None) -> Ask \| None` | **拉**模式用。超时返回 `None`,被取消则抛 |
| `answer` | `(ask_id: str, text: str) -> bool` | 回答。`False` = 这个提问已不在等(超时 / 已答) |
| `decline` | `(ask_id: str, reason: str = "") -> bool` | 跳过,让模型自己判断 |
| `transcript` | `() -> str` | 问答记录的 markdown |

**两种取法选一种**:**推** —— 构造 `HumanChannel(on_event=...)`;**拉** —— `await channel.next_ask()`。
`Workflow.run` 只在 `channel.on_event is None` 时才自动接线,所以自己传了就不会被覆盖。

**跨线程**:`answer` / `decline` / `send` 内部走 `loop.call_soon_threadsafe`,
Web 后端 / TUI 输入线程直接调是常态。

三个"0 / None"语义各不相同,别记混:`max_asks=None` = 不限、`max_asks=0` = 不许问;
`timeout_s=None` = 永远等、`timeout_s<=0` = 立刻超时;`remaining` 在 `max_asks=None` 时是 `-1`。

未导出但会出现在返回值里的 `Mail` 是一个 dataclass,字段 `id` / `text` / `sent_at` / `taken`。

---

## 血缘 {#血缘}

源码:[`flower/core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py)

### `Lineage` {#lineage}

```python
@dataclass
class Lineage:
    path: Path
    workspace: Path
    steps: dict[str, str] = field(default_factory=dict)
    woke: int = 0
```

跨进程记录"哪一步用了哪条会话",[接续](glossary.md#接续)靠它找到上次跑到哪。
文件是 `<run_dir>/lineage.json`。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `path` | `Path` | 必填 | 血缘文件路径 |
| `workspace` | `Path` | 必填 | 工作区。`__post_init__` 会 resolve |
| `steps` | `dict[str, str]` | `{}` | 步骤名 → `session_id` |
| `woke` | `int` | `0` | 唤醒过几次 |

| 成员 | 签名 | 说明 |
|---|---|---|
| `open` | `@classmethod (run_dir: str \| Path, workspace: str \| Path) -> Lineage` | 读 `<run_dir>/lineage.json`。**文件不存在、读不动、或 `workspace` 字段对不上,一律返回空的,不报错** |
| `remember` | `(step: str, session_id: str) -> None` | 记住映射并**立刻落盘**。空 step 或空 sid 直接返回 |
| `bump` | `() -> int` | 唤醒计数 +1,落盘,返回新值(第一次跑是 `1`) |
| `archive` | `(into: str \| Path, *, extra: list[Path] \| None = None) -> Path` | 把血缘文件 + `extra` **移动**到 `<into>/<YYYYmmdd-HHMMSS>/`,并把 `steps` / `woke` 清零。**移动不是删除** |

落盘走 `tmp.replace(path)` 原子替换;`OSError` 静默吞掉 —— 落盘失败不该带走这次运行。

**`workspace` 是守卫**:SDK 的 `project_key` 从工作区路径推导,目录被拷走后旧 `session_id` 查不到,
所以路径对不上就当没有。

`Workflow.run` 装载血缘时,会对每条记录逐个用 `runtime.has_session(sid)` 验证还在库里,活着才用 ——
血缘文件可能比 `sessions.db` 活得久。

---

## 最小可用示例 {#示例}

五段都能直接跑。前提:装好 `claude-agent-sdk`,`ANTHROPIC_API_KEY` 或 `ANTHROPIC_AUTH_TOKEN` 可用
(否则 `Runtime(...)` 构造时就抛 `RuntimeError`)。

### 一个 agent 跑一步 {#示例-单-agent}

最小骨架:声明一个 `AgentSpec`,建一个 `Runtime`,`await rt.run(...)`,读 `StepResult`。

```python
import asyncio
from pathlib import Path

from flower import AgentSpec, Runtime

spec = AgentSpec(
    name="reader",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob", "Grep"],
    max_turns=4,
)


async def main() -> None:
    rt = Runtime(workspace=Path("."), run_dir="runs")
    try:
        r = await rt.run(spec, "读 README.md,一句话说它是干什么的。",
                         on_event=lambda ev: print(ev))
        print(f"ok={r.ok} session={r.session_id} ${r.cost_usd:.4f} {r.duration_s}s")
        print(r.text)
    finally:
        rt.close()


asyncio.run(main())
```

`Runtime` 的参数**全是 keyword-only**;`rt.run()` 的 `spec` 和 `prompt` 是位置参数,其余 keyword-only。
`AgentSpec` 默认 `allowed_tools=["Read", "Glob", "Grep"]`、`delegate_only=False`,
所以 `Runtime` 会自动给它装 [`whitelist_guard`](#whitelist-guard),把 `Bash`/`Write`/`Edit`/`NotebookEdit` 全拦掉。

### 协调者 + 执行者 {#示例-协调}

一个不动手的[协调者](glossary.md#协调者)带一个干活的[执行者](glossary.md#执行者)。
这是 flower 省上下文的第一层。

```python
import asyncio
from pathlib import Path

from flower import Runtime, coordinator, worker


async def main() -> None:
    analyst = worker(
        "分析文件内容:统计、查找、比对。要真读文件、跑命令的活派给它。",
        "你负责在 data/ 下做文本分析。用命令行完成,不要手工估算。",
        tools=["Read", "Write", "Bash", "Glob", "Grep"],
    )
    boss = coordinator(
        "主控",
        "目标:摸清 data/ 下几个文件的规模。做完给一句话结论。",
        {"分析员": analyst},
        max_turns=14,
        max_budget_usd=1.5,
    )

    # workbench=True 必须给:delegate_guard 挂在 workbench_hooks 里,
    # 不开工作台的话协调者的 Bash/Write 没有任何 hook 拦。
    rt = Runtime(workspace=Path("."), run_dir="runs", workbench=True)
    try:
        r = await rt.run(boss, "统计 data/ 下每个 .txt 的行数和总字符数,告诉我哪个最大。",
                         on_event=lambda ev: None)
        print(f"ok={r.ok} turns={r.num_turns} ${r.cost_usd:.4f}")
        print(r.text)
    finally:
        rt.close()


asyncio.run(main())
```

`worker()` 的前两个参数是位置的:`description`(协调者用来选人)、`prompt`(它的 system prompt,
后面自动拼 `WORKER_RULES`)。`coordinator()` 的前三个是位置的:`name`、`instructions`、`workers`。

### 自己写一个 Workflow {#示例-workflow}

两步,后一步把前一步的结果注入自己的 prompt —— 便宜、隔离,不共享会话。

```python
import asyncio
from pathlib import Path

from flower import AgentSpec, Runtime, Step, Workflow

terse = AgentSpec(
    name="terse",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


async def main() -> None:
    wf = Workflow([
        # 新会话:只吃 prompt 里的东西
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # 新会话 + 上一步结果注入 prompt(便宜、防污染)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
        # 想接着同一个会话说就写 resume_from="造句";要分叉再加 fork=True
    ])

    rt = Runtime(workspace=Path("."), run_dir="runs")
    try:
        ctx = await wf.run(rt, on_step=lambda s, r: print(f"{s.name} ok={r.ok} {r.text[:40]!r}"))
    finally:
        rt.close()

    print(ctx["造句"])                 # ctx[step.name] = result.text(没给 reduce 时)
    print(ctx["_sessions"])            # step name -> session_id
    print(ctx.get("_failed_at"))       # on_fail="stop" 时失败在哪一步


asyncio.run(main())
```

`Step` 的前三个字段(`name` / `spec` / `prompt`)是位置参数,`Workflow` 的 `steps` 也是。
`Workflow.run(runtime, *, on_event=None, on_step=None)` —— `runtime` 位置,两个回调 keyword-only。
**注意 `continuous=True` 是默认值**:同一个 `run_dir` + 同一个 `workspace` 第二次跑时,
`resume_from=None` 的步骤也会接着上次那条会话说。

### 加一道目标看守 {#示例-目标}

先让[判定者](glossary.md#判定者)把目标和判定清单定下来,再让干活那步接受判定 ——
判不过就带着反馈重来,最多三轮。

```python
import asyncio
from pathlib import Path

from flower import (HumanChannel, Runtime, Step, Workbench, Workflow,
                    coordinator, goal_step, with_goal, worker)


async def main() -> None:
    wb = Workbench(Path.cwd()).ensure()
    # timeout_s=0 = 全自动:所有提问立刻落空,不假装等人
    ch = HumanChannel(log_path=wb.notes / "问答记录.md", timeout_s=0)
    goal_path = wb.notes / "目标.md"

    coord = coordinator("协调者", "", {
        "coder": worker("写代码与测试。要动手实现的活派给它。",
                        "你负责实现。每改一处就跑一次验证,别攒到最后。"),
    }, channel=ch)

    work = Step("干活", spec=coord, prompt="把 hello.py 写出来,跑 `python hello.py` 要打印 hello。")
    # rounds 是**总轮数**:rounds=3 → retries=2 → 最多跑三轮活
    work = with_goal(work, ch, goal_path=goal_path, rounds=3, can_run=True)

    wf = Workflow(
        [goal_step(ch, goal_path=goal_path), work],
        channel=ch,
        workbench=wb,
        # goal_step 的 prompt 读 ctx["确认需求"](brief_key 默认值)。
        # 没有 clarify_step 时自己灌一份,否则它只会看到 "(没有确认书)"。
        context={"确认需求": "## 目标\n写一个打印 hello 的 python 脚本\n\n## 验收标准\n跑 `python hello.py` 输出 hello"},
    )

    rt = Runtime(workspace=Path.cwd(), run_dir="runs", workbench=wb)
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()

    print(ctx["_goal"])        # GOAL_KEY:Goal 对象
    print(ctx["_verdict"])     # VERDICT_KEY:最近一次 Verdict
    print(ctx["_goal_rounds"]) # ROUND_KEY:跑了几轮
    print(ctx.get("_aborted")) # StepAbort 的原因(无法达成且无人应答时)


asyncio.run(main())
```

`with_goal` 只换掉 `gate` / `on_reject` / `retries`,其余字段用 `dataclasses.replace` 原样带过去。
判定者是**独立会话**:`gate` 内部单独调 `rt.run(judger, ..., step_name=f"{label}#{轮次}")`,
`resume` 恒为 `None`。

### 换掉交互层 {#示例-交互层}

要把终端换成 Web / TUI / HTTP,只需要改两个东西:渲染 `Event` 的那个函数,和取提问的那个协程。

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """把 Event 渲染成你自己的 UI —— 这是唯一需要换的东西。"""
    if ev.kind == "step":
        print(f"\n=== {ev.text} ({ev.payload['index']}/{ev.payload['total']}) ===")
    elif ev.kind == "text" and not ev.payload.get("subagent"):
        print(ev.text)
    elif ev.kind == "tool_call":
        print(f"  [{ev.tool}] {ev.text}")
    elif ev.kind == "handoff":
        print(f"  ~ handoff/{ev.payload.get('phase')}: {ev.text}")
    elif ev.kind == "retry":
        print(f"  ~ retry: {ev.text}")
    elif ev.kind == "ask" and ev.payload.get("kind") == "mail":
        print(f"  ~ 人主动说:{ev.text}")
    # kind == "ask" 且不是 mail 的,交给下面的 answerer 处理(拉式)


async def answerer(ch: HumanChannel) -> None:
    """拉式取提问。换成 Web 后端 / HTTP 服务时,这个协程是唯一要改的地方。"""
    while True:
        ask = await ch.next_ask()          # 无 timeout 时会一直等
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")   # 或 ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime 用 workflow 自己建好的工作台 —— 别另拼一个
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()


asyncio.run(main())
```

推和拉**选一种**:推是构造 `HumanChannel(on_event=...)`,拉是 `await channel.next_ask()`。
`Workflow.run` 只在 `channel.on_event is None` 时才自动接线,所以自己传了 `on_event` 就不会被覆盖。
`answer()` / `decline()` / `send()` / `interrupt()` **都可以从别的线程调**。

---

## 陷阱与易错点 {#陷阱}

按会踩到的顺序排,不按模块。每条都有实测出处。

### 装配 {#陷阱-装配}

1. **`Runtime(workbench=False)` + `coordinator()` = 主线程一道墙都没有。**
   `delegate_guard` 只在有工作台时装,`whitelist_guard` 又被 `delegate_only=True` 跳过。
   用协调者就把工作台打开。详见 [Runtime](#runtime)。
2. **工作台位置有两个,别拼错。** `Runtime(workbench=True)` 落在 `<run_dir>/workbench`;
   `Workbench(ws)` 默认是 `<ws>/.flower`。自己拼 `brief_path` 时按后者写,
   **确认书写进 A 目录、注入的索引扫的是 B 目录,而且不报错**。
   正确做法:workflow 自己 `Workbench(...).ensure()` 挂到 `Workflow.workbench`,
   再把**同一个对象**交给 `Runtime(workbench=wb)`。
3. **`allowed_tools` 不是排他白名单,是免审批清单。** 模型照样能调不在里面的工具。
   `clarify()` / `judge()` 的"没有写工具"靠的是 [`whitelist_guard`](#whitelist-guard) 这道 hook。
   而 `coordinator()` 默认 `permission_mode="acceptEdits"` —— 谁把这个值传给
   `clarify()` / `judge()`,保护就没了。
4. **`disallowed_tools` 是会话级的**,会把 subagent 的同名工具一起禁掉。
5. **工作台索引进不了 subagent。** "长产出写 `artifacts/`"必须由协调者在任务书里转述,
   那是唯一通道。
6. **`Runtime(...)` 在没有凭证时构造阶段就抛 `RuntimeError`**,不是等到 `run()`。
7. **`Runtime.run_id` 必须每实例唯一。** `manifest.json` 按 `run` 字段去重,两个 id 撞上时
   后写的会把对方的行当成"自己上次写的"删掉。

### 流程 {#陷阱-流程}

8. **`Workflow.continuous=True` 是默认值**,`resume_from=None` 不等于"全新会话"。
   要每次都新开就显式 `continuous=False`。**改了步骤名就等于断了血缘。**
9. **`with_goal(rounds=N)` 是总轮数,不是额外轮数**:`retries = max(0, rounds - 1)`。
10. **`on_fail="skip"` 不写 `ctx[step.name]`** —— 下游 `lambda ctx: ctx["某步"]` 会 `KeyError`。
    要带着残缺结果往下走用 `on_fail="continue"`。
11. **`resume_from` 指向未运行 / 已失败的步骤会抛 `ValueError`**,不是静默跳过。
12. **`Step.reduce` 必须是同步函数;`gate` / `when` / `on_reject` 可以是 async。**
13. **`fork=True` 不给 `resume` 时静默无效。** `Workflow` 从不传 `resume_at`,
    要按消息回滚只能直接调 `Runtime.run`。
14. **自己驱动 `Runtime` 时,`on_session` 必须在 gate 之前摘掉**,否则判定者的会话会被写进
    干活那一步的血缘。`Workflow` 用 `try/finally` 保证了这一点。
15. **`step_name` 决定 manifest 和血缘里的键。** `Workflow` 会加 `#retryN` / `#roundN` 后缀,
    判定者加 `#轮次` —— **带后缀的名字不进跨进程血缘**,这正是"判定者永远是新会话"的实现方式之一。

### 角色 {#陷阱-角色}

16. **`clarify(max_turns=<小数字>)` 会把"提问不限次数"变成空话** —— 每次提问就是一轮。
17. **`goal_step()` 没有 `can_run` 形参**,只能走 `**spec_kw` 传 `can_run=True`。
    不传的话设目标的判定者拿不到 `Bash`,`JUDGE_RULES` 里"先看清楚你在什么环境"那条执行不了。
18. **`judge(can_run=True)` 让判定者能改动工作区** —— `whitelist_guard` 从 `allowed_tools` 派生,
    给了 `Bash` 就放行 `Bash`(仍拦 `Write`/`Edit`,但 `Bash` 本身能写文件)。要绝对中立就别开。
19. **`worker(isolate=True)` 要求 workspace 是 git 仓库**,否则 `Agent` 工具直接报
    `"not in a git repository"`,不会静默退化。而且隔离标记是 Python 属性,
    **对 `AgentDefinition` 做 `dataclasses.replace()` 会丢掉它**。
20. **直接构造 `AgentDefinition` 时参数是驼峰**:`maxTurns`、`permissionMode`。
    `worker()` 已经替你转过了。

### 换代与上下文 {#陷阱-换代}

21. **换代开着时 auto-compact 被强制关掉,没有兜底。** 所以写交接那一步必须有降级路径。
    要保留 auto-compact 就显式给 `AgentSpec.compact`。
22. **`HandoffPolicy.window` 配小了会无限换代烧钱。** 唯一的闸是 `max_generations=8`。
    另一头,**`default_window()` 在两个环境变量都没设时也返回 `1_000_000`** ——
    判大了靠 `is_overflow()` 兜住(变成一次降级换代),不是硬错,但那一代的交接是降级的。
23. **没有工作台时交接不落盘。** 文书照样通过 prompt 交给接手者,但人事后翻不到。

### 存储 {#陷阱-存储}

24. **`Runtime(trim=False)`(默认)不等于"什么都不清"。** store 永远是 `PruningSessionStore`,
    `trim=False` 只关掉大结果裁剪;**摘断线残渣、摘被拒调用、中断残留中性化、时效性过期照做。**
25. **两个 spill 目录不是同一个**:`spill_guard` 落在 `<workbench.root>/spill/`,
    `TrimPolicy.spill_dirname` 落在 `<workspace>/.flower/spill/`(必须在工作区内)。
26. **`PruningSessionStore.__init__` 的第四个位置参数是 `prune` 不是 `ephemeral`**,
    和父类不同。按位置传会静默错位。

### 文书与交互 {#陷阱-文书}

27. **`Verdict` 解析不出结论时 `state=""`、`ok=False`,绝不能当成达成。**
    另外"无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable"全部归到 `unreachable`,
    会触发"停下来问人"那条路,不是"再来一轮"。
28. **`Brief.parse` 遇到未闭合的代码围栏会丢弃它之后的全部内容** —— 模型输出被截断时,
    后面的段全解析不出来,`complete()` 为 `False`,gate 打回重来。
29. **`Brief.load` 把 `"(未填)"` 当空。** 手工编辑确认书时照抄了占位文字,那一段仍算缺失。
30. **`HumanChannel` 的三个"0 / None"语义各不相同**:`max_asks=None` 不限、`max_asks=0` 不许问;
    `timeout_s=None` 永远等、`timeout_s<=0` 立刻超时;`remaining` 在 `max_asks=None` 时返回 **`-1`**。
31. **`Event("ask")` 同时承载提问和人主动说的话**,后者 `payload["kind"] == "mail"`。UI 要先判它。
32. **`Workflow.run` 只在 `channel.on_event is None` 时才自动接线** ——
    自己构造 `HumanChannel(on_event=...)` 的话,提问事件不会同时进 workflow 的 `on_event` 出口。
