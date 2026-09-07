# flower 文档

flower 是一个**可移植的长程 agent 框架**。它用 Claude Agent SDK wheel 里自带的原生二进制
发请求 —— 不需要装 Claude Code CLI、不需要 Node、不读宿主机的 `~/.claude/`。
在 Claude Code 的原生系统提示词**之上叠加**领域指令,所以专业化不以损失通用能力为代价。

它**不**替你设计工作流。框架只管机制:一步怎么跑、上下文怎么省、断网怎么续、
并行改同一个仓库怎么不打架、需要问人的时候怎么停下来。**流程是你的活。**

| 想干什么 | 读哪一篇 |
|---|---|
| 装上、跑通第一个 | 本页 ↓ |
| 设计自己的流程(`Step` / `Workflow` 参考) | [workflow.md](workflow.md) |
| 让它先把需求问清楚再动手 | [clarify.md](clarify.md) |
| 谁来判"做完了没有" | [goal.md](goal.md) |
| **同一个目录再跑一次,它还记得吗** | [continuity.md](continuity.md) |
| **上下文满了怎么办(不 compact)** | [handoff.md](handoff.md) |
| **一次真实运行到底发生了什么(实测数据)** | [case-ht001.md](case-ht001.md) |
| **目标看守首次真实运行,以及它把简单问题复杂化了** | [case-ht002.md](case-ht002.md) |
| 换掉终端,接 Web / TUI / HTTP / 全自动 | [interaction.md](interaction.md) |
| 为什么是这些设计(实测数据、踩过的坑) | [../README.md](../README.md) |

---

## 装

需要 Python ≥ 3.10。唯一的运行依赖是 `claude-agent-sdk`,原生二进制在它的 wheel 里。

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env        # 填 ANTHROPIC_AUTH_TOKEN

# 让 flower 在任何目录都能用(shebang 是绝对路径,软链就够)
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

`.env` 已被 gitignore。**凭证必须自带**:flower 用 `setting_sources=[]` 隔绝了宿主机配置,
连 `~/.claude/settings.json` 里的 `env` 块也不读 —— 这是可移植性的代价,也是它换台机器
行为一致的原因。优先级:进程环境 > 仓库根 `.env`。

第三方网关填 `ANTHROPIC_BASE_URL`;官方端点留空。加 `-v` 会在启动时打印生效端点
(token 打码),免得连错网关还不自知。

## 跑通第一个

先证明凭证和二进制都通 —— 单 agent,只读工具,几分钱:

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

## 一键跑起来

不用先写任何代码,也**不用在 shell 里打引号**。进你的项目目录,直接:

```bash
cd /path/to/your/project
flower
```

它会问你要做什么,光标等着:

```
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

诉求走标准输入,不经过 shell 解析 —— 中文引号、空格、感叹号都能直接打。
(为什么值得单独做:命令行里那对引号是纯负担。实测踩过 —— 右引号打成中文的 `”`,
zsh 会一直等真正的右引号,看起来像程序卡住,其实一次都没启动。)

要写脚本或者一行搞定时照样可以给参数:

```bash
flower "帮我做一个 X"
echo "帮我做一个 X" | flower --timeout 0     # 全自动,不等人
```

三步:

1. **先问清楚**(`❓` + 编号选项:输序号、打字回答,或直接回车让它自己判断)——
   问几次由它自己决定,**没有次数上限**。需求冻结成 `.flower/notes/需求.md`。
2. **把需求变成可判定的目标**,冻结成 `.flower/notes/目标.md`。
3. **干活,每轮结束由独立的判定者判"做完了没有"** —— 没达成就打回去接着做,
   做不到就停下来问你。见 [goal.md](goal.md)。

**重跑就是接着上次说。** 同一个目录再跑一次 `flower`,每一步接着上次那个会话 ——
不会再盘问一遍需求,也不会重设一遍目标,连协调者试过哪些死路都还记得。
进程被 kill、机器重启都一样。什么都不想说就直接回车:

```
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 顺便支持代码块高亮
↩ 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

唤醒时说的那句话会追加进 `需求.md`,并触发重新推导判定清单 ——
否则判定者读的还是老清单,你新加的事根本不进判定。细节和代价(**上下文会一直涨**)
见 [continuity.md](continuity.md)。

| 开关 | 作用 |
|---|---|
| `--clarify-only` | 只问清需求,不往下干活(便宜,先看看它问什么) |
| `--asks N` | 提问额度,**默认不限**;给个数字就是硬额度,`0` 不许提问 |
| `--rounds N` | 干活的总轮数上限(默认 3)|
| `--no-goal` | 关掉目标看守 —— 跑完就算完,不判定 |
| `--judge-can-run` | 让判定者能跑命令(判定更硬,但它能改动工作区)|
| `--timeout 秒` | 等你多久,默认 1800;**`0` = 全自动,没人时不阻塞** |
| `--isolate` | 每个 subagent 分一份 git worktree(要求项目是 git 仓库) |
| `--window N` | 模型窗口,**默认 100 万**(名字带 `haiku` 的按 20 万)。到 窗口−50000 就写交接换新会话,而不是 compact |
| `--no-handoff` | 关掉换代,退回 SDK 的 auto-compact |
| `--new` | 这次别接上次:上一段的需求/目标/血缘收进 `notes/archive/`(不删,只是移开) |
| `-v` | 显示思考和工具结果 |

开关写在诉求前面或后面都行,只给开关不给诉求也行(`flower --clarify-only` 会先问你要做什么)。这条路径的流程实现在
[`flower/workflow/starter.py`](../flower/workflow/starter.py) —— 两步,通用到不含任何领域假设。

> **要在真终端里跑。** 回答提问走标准输入,管道/`nohup`/CI 里没人能答:
> 第一个问题会被当成"输入已关闭"跳过,之后每个问题都要干等满 `--timeout`。
> 无人值守就显式给 `--timeout 0`。

## 换成你自己的流程

`starter.py` 那两步是给你起步用的,**领域流程是你的活**。写一个 `flows.py`:

```python
# flows.py —— 放在你自己的项目里,在项目目录内运行
from pathlib import Path
from flower import (HumanChannel, Step, Workbench, Workflow,
                    clarify_step, coordinator, worker)

def main():
    # 工作台自己建,然后挂到 Workflow 上交给驱动 —— 别只拼一个路径。
    # 理由见下面「工作台要挂在 workflow 上」。
    wb = Workbench(Path.cwd()).ensure()
    ch = HumanChannel(log_path=wb.notes / "问答记录.md", max_asks=6, timeout_s=1800)

    主控 = coordinator("主控", "", {
        "coder": worker("写代码与测试。要动手实现的活派给它。",
                        "你负责实现。每改一处就跑一次验证。"),
    })

    return Workflow(channel=ch, workbench=wb, steps=[
        clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
        Step("干活", spec=主控, prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
    ])
```

```bash
cd /path/to/project
flower -T run flows.py:main
```

第一步会**问你几个问题**(`❓` + 编号选项:输序号、打字回答,或直接回车让它自己判断),
问完把需求冻结成 `.flower/notes/需求.md`;第二步才开始干活。重跑不会再盘问一遍。
详见 [clarify.md](clarify.md)。上面这段的完整可抄版本是
[`examples/trial.py`](../examples/trial.py)。

### 工作台要挂在 workflow 上,不能只拼路径

`Workflow` 有两个字段是给**驱动程序**看的,`cli.py` 会自动发现:

| 字段 | 驱动拿它做什么 |
|---|---|
| `channel` | 知道该向谁回答提问(接标准输入 / Web 后端) |
| `workbench` | 交给 `Runtime`,而不是自己按 `-W` 造一个 |

第二条是必须的,不是风格问题。`brief_path`、`log_path` 这类文件**必须落在真正被注入
索引的那个工作台里** —— 索引进的是每个 agent 的 system prompt,后面每一个 subagent
开局才知道需求文件在哪。而 `-W`(即 `Runtime(workbench=True)`)的默认位置是
`<run_dir>/workbench`,`main()` 被 CLI 调用时**看不到** `run_dir`,自己拼只会拼到别处:
**确认书写进 A 目录,注入的索引扫的是 B 目录,那条承诺就静默失效了 —— 不报错。**
把工作台建好再挂上去,两边用的就是同一个对象。(`tests/trial_offline.py` 钉住了这一条。)

开 worktree 隔离(`worker(..., isolate=True)`)时,工作台要放到**仓库外**:
`Workbench(Path.cwd(), home=Path.cwd().parent / ".flower-proj")` —— worktree 是每个
agent 的私有副本,工作台是跨 agent 的共享层,共享的东西不能放进私有围栏里。
放外面时 `Runtime` 会自动 `add_dirs` 授权。

常用开关:

| 开关 | 作用 |
|---|---|
| `-w PATH` | agent 的工作目录(默认当前目录) |
| `-W` | 开工作台:脚本/产出/笔记落盘,索引注入**主 agent** 的 system prompt(subagent 继承不到,见 [workflow.md](workflow.md)) |
| `-T` | resume 时把旧的大工具结果换成文件指针 |
| `-v` | 打印生效端点、思考过程、工具结果 |
| `-r DIR` | 会话库与运行清单的位置(默认 `runs/`) |

## 五分钟看懂全局

```
 你写的 flows.py
    │
    ├── Workflow([Step, Step, ...])        ← 你的流程(领域逻辑,框架不碰)
    │      │      └ spec=AgentSpec         ← 每步用哪个角色:指令 + 工具白名单 + 预算
    │      └ channel=HumanChannel          ← 需要停下来问人时挂它
    │
    └── Runtime(workspace=..., ...)        ← 跑一步 = 一个 session
           ├── SessionStore   SQLite 落盘 → 断线残渣摘除 → 过期/大结果剪枝
           ├── hooks          拦主线程的 Bash / 大结果落盘 / worktree 隔离
           └── Event 流 ──────────────────→ 你的 UI(cli.py 是 200 行的参考实现)
```

一句话串起来:**`Workflow` 按顺序把 `Step` 交给 `Runtime` 跑,每跑一步产生一个 session
和一串 `Event`;上下文的省法由角色分工和 store/hook 决定,和你的流程正交。**

四条贯穿全局的取舍,理由在 [../README.md](../README.md) 里都有实测数据:

1. **叠加不替换** —— `system_prompt` 用 preset `claude_code` + `append`。别的专项 agent 弱,
   多半是因为把系统提示整个换掉了。
2. **主 agent 不动手** —— 它没有 Bash/Write/Edit,一切派给 subagent。subagent 的试错
   进的是**另一条 transcript**,主线程只收报告。实测一次重活 83% 的内容沉在 subagent 里。
3. **琐碎沉到磁盘** —— 工作台 `.flower/{scripts,artifacts,notes}` 的索引注入 system prompt。
   压缩清得掉上下文,清不掉磁盘。
4. **拿不准就先问** —— 剪枝清的都是现场,而"目标理解错了"是唯一一类**剪枝会让它变严重**
   的错误。所以有一个前置确认步骤,把需求冻结成文书再开工。

## 概念速查

| 概念 | 一句话 | 在哪 |
|---|---|---|
| `AgentSpec` | 一个 agent 的完整声明:指令、工具白名单、模型、预算、subagent 名册 | `core/agent.py` |
| `coordinator()` | 造一个只协调不动手的主 agent(工具只有 Agent/TodoWrite/Read + 受限 Bash) | `core/roles.py` |
| `worker()` | 造一个干活的 subagent 定义,交给 `coordinator` 派 | `core/roles.py` |
| `clarify()` | 造一个只提问不动手的确认者(没有任何写工具) | `core/roles.py` |
| `Runtime` | 执行核心。跑一次 = 一个 session:落盘、重试、装 hook、算钱 | `core/runtime.py` |
| `StepResult` | 一步的结果:`text` / `session_id` / `cost_usd` / `ok` / `attempts` | `core/runtime.py` |
| `Step` `Workflow` | 你的流程。三种会话接法 + `when`/`gate`/`reduce`/`retries` | `workflow/base.py` |
| `Workbench` | 磁盘沉淀层 + 索引注入 | `core/workbench.py` |
| `HumanChannel` | 唯一一处"停下来等人"。模型侧是一个 MCP 工具 | `core/human.py` |
| `Brief` | 冻结的四段需求确认书 | `core/brief.py` |
| `Event` | UI 的唯一边界。UI 不 import 任何 SDK 类型 | `core/events.py` |

## 一次运行留下什么

```
runs/
  sessions.db        全部 transcript(含每个 subagent 的独立 transcript)。原文永不改写
  manifest.json      step → session_id / 花费 / 重试次数 / 失败原因。**跨进程追加**
  lineage.json       步骤名 → session_id。同一个目录再跑一次就靠它接上
  workbench/notes/交接-*.md   换代留下的交接书。可读可改,接手的会话读的就是它
  workbench/         开 -W 时的工作台:scripts/ artifacts/ notes/ + INDEX.md
```

`manifest.json` 是**血缘记录**:每一步的 `session_id` 都在里面,所以事后任意一步都能
被续跑、分叉或回滚(见 [workflow.md](workflow.md) 的「事后再来一次」)。
重试历史、错误原文也只记在这里 —— **模型看不到**。

## 花多少钱

框架本身不额外收费,花的都是模型调用。几个实测参考值:

| | 花费 |
|---|---|
| 一个 subagent 的启动地板(不可摊薄) | ~4.3k tokens |
| 协调者的启动地板 | ~34k tokens |
| `tests/smoke.py` 单 agent 全链路 | ~$0.21 |
| `tests/flow_demo.py` workflow 三种接法 | ~$0.39 |
| `tests/delegation.py` 分工 + 量上下文分布 | ~$0.71 |
| `tests/isolation.py` 三个 issue 三个 worktree | ~$0.9 |
| 一次不受约束的需求澄清(反面教材,见 clarify.md) | $0.8908 / 230s |

不花钱的离线验证:

```bash
.venv/bin/python tests/clarify.py    # 前置确认:提问通道 / 四段解析 / 角色白名单 / 接线
.venv/bin/python tests/flow_offline.py  # Workflow.run 的执行语义(假 Runtime,不打网络)
.venv/bin/python tests/glance.py     # 放行白名单与过期剪枝的互补性不变式
.venv/bin/python tests/denial.py     # 被拒调用清理 + transcript 链完整性
```

熔断闸:`AgentSpec(max_budget_usd=...)` 是硬上限,`Runtime.total_cost()` 是当次合计。

## 排错

| 症状 | 原因与处理 |
|---|---|
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN` | flower 不读 `~/.claude/settings.json`。写进仓库根 `.env` 或进程环境 |
| 连错端点 / 模型不对 | `-v` 启动时会打印 `describe()`:生效的 BASE_URL 与模型映射 |
| `not in a git repository` | 用了 `worker(isolate=True)`,但 workspace 不是 git 仓库。这不会静默退化 |
| subagent 报"写入权限被拒",脚本落不了盘 | 工作台在工作区外时必须 `add_dirs` 授权。`Runtime(workbench=True)` 已经处理;自建 `Workbench` 要自己给 |
| 被隔离的 agent 写不进工作台 | worktree 是私有副本,工作台是共享层,不能放进私有围栏。默认放 `run_dir/workbench`(仓库外)就是为这个 |
| `步骤 'X' 要求 resume_from='Y',但那一步没有产生 session` | `Y` 被 `when` 跳过了、失败了,或根本没跑过。`resume_from` 只能指向真的产生过 session 的步骤 |
| 提问一直没人答 | `HumanChannel(timeout_s=...)` 到点返回一句说明让模型自己判断,不报错。`timeout_s=0` = 全自动 |
| 活干完了还要按一次回车才退出 | 别用 `asyncio.to_thread(input, ...)` 读标准输入 —— `input()` 取消不掉。用 daemon 线程,`cli.py:answer_from_stdin` 是参考实现 |
| 主 agent 学会了"Bash 反正会被拦",连 `git status` 都不试了 | 被拒调用堆在上下文里造成的。`Runtime(keep_denials=1)` 默认已清,别调大 |
