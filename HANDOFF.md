# HANDOFF

> 写给下一个接手 flower 的 session。**读完这一份就能接着干**,不必翻上游 transcript。
> 上次更新:2026-09-09(第五轮:公开发布 + 终端安全 + 换代机制 + 一批取证与 issue)。
> 上一轮(第四轮,2026-09-06/07)的 HANDOFF 已归档到 `archive/HANDOFF-2026-09-07-r4.md`
> —— 它的 §1 死约束和 §6 地雷仍然成立,这一份把它们更新到当前。
>
> **本轮的事实基础**:代码地图、测试状态、承重数字都是这一轮亲手 grep / 实跑核对过的,
> 不是凭记忆。凭记忆写 API/定价的事实这一轮栽过三次(见 §8),别再犯。

---

## 0. 一句话现状

框架主体成型、九个离线测试全绿、已**公开发布**(GitHub 仓库 `ChenyuHeee/flower`
+ Pages 文档站 + 一句话安装)。这一轮没有加大功能,做的是**让它在真实长程运行里
不炸、不烧冤枉钱**:终端安全、并行写锁、换代机制、打断续跑、凭证探针、自动更新,
外加四次终端崩溃的取证和一批止损 issue(#20–24)。

**用户此刻有一个 flower 正在 `~/research/explore/AI4S/` 跑**(一篇论文/文档类任务)。
它撞上了 §6.7 那个窗口误判 bug —— 网关给的是 200K 窗口的 `claude-opus-5`,而 flower
按名字判成了 1M,于是在 174K 溢出、走降级空交接。**救法:`flower --window 200000`
同目录重启,血缘会接上。** 别的先别动,尤其别碰它的目录。

---

## 1. 用户定的死约束 —— 不要重新讨论,不要"优化"掉

(与上一轮一致,仍然成立。)

1. **可移植的、专门的 agent**。不是针对这台机器的定制。
2. **必须脱离 claude CLI**。只靠 SDK wheel 内置二进制发请求(`setting_sources=[]`)。
3. **交互方式可定制**。不绑终端 TUI —— 提问以 `Event(kind="ask")` 浮出,谁来答都行。
4. **长程 agent workflow**。
5. **workflow 的领域设计是用户的活,不是你的活。** 原话:
   > "我想要的是一个长程的 agent workflow,我在你确定好了框架之后可以开始设计。"

   你负责机制(Step/Workflow/角色/剪枝/隔离/确认/换代),他负责流程。
   **不要替他设计领域工作流,不要问他做什么项目、用什么语言** —— 问过,他没答,
   等于回答了:框架不该知道这些。

动机前提(所有取舍的依据):
> "别的专项 agent 或者通用 agent 都没有 claude code 强大"

**可移植性不能拿能力换。** 所以是"在 Claude Code 原生能力之上叠加",不是重写一个 agent。

贯穿全局的上下文经济学(用户自己提的):
> "把所有具体写代码、测试、调用工具的能力都丢给 subagent……主 agent 扮演正常使用
> Claude Code 的使用者,协调不同 subagent……上下文就只剩下决策。"

**这一轮新验证到的一条推论**(见 §6.5):这套经济学是成立的 —— novel 那次缓存把
约 $899 的裸价压到约 $234,而且 79% 的花费确实发生在一次性的 subagent 子上下文里。
剩下的浪费不是缓存策略问题,是**重复干活**(正确性 bug),不是经济学问题。

**关于省钱,一条容易读歪的历史**:归档 HANDOFF §2(archive:84)记着用户"我不用省 token,
直接全量跑,别再往省钱方向劝"。**那句的语境是"别劝我用 `--clarify-only` 这种省钱档、
别拿功能换便宜"**。这一轮(2026-09-09)用户明确要"从底层逻辑省钱,**在对质量毫无影响的
前提下**"。两者不矛盾,共同的不变量是:**不拿质量换钱**。所以 `effort`/换小模型这类
省法排除;缓存前缀这种"信息一字不少只换位置"的结构性省法(#22)是他要的。

**这一轮新增的一条用户决定**(2026-09-09):放弃"多开检测闸"。用户一度要求
"启动时检测已有 flower,让人选杀掉接管还是退出",但实测证明多开可以做到安全
(见 §6.1),不该用禁用能力来换。`_TtyGuard` 里"并行是正常用法,不该靠别开两个
回避"那句话继续成立。

---

## 2. 用户现在在等什么

1. **救回正在跑的那个 run**(AI4S,见 §0)—— `--window 200000` 重启。这是最紧的。
2. **他自己在重写 `docs/`** —— 明确说过"不需要你帮忙"。**别碰 docs/**。
3. 这一轮开的 5 个 issue(#20–24)都还没动手 —— 用户说"先进 issue",没说现在修。
   **别自己找活干**,等他挑。

---

## 3. 这一轮(第五轮)做了什么:commit → 为什么

按主题归类(旧 HANDOFF 之后的 25+ 个 commit):

- **终端安全**(`c873d2d`):只喂 ASCII、消毒转义、硬性不超宽。起因两次 Terminal 崩溃。
- **并行写锁**(`0b2ef1e` / `71fd114`):跨进程 tty 写锁,限时抢(不阻塞),账本并行安全。
- **接续 = 同路径**(`c1bd96c` / `17f9313`):`Lineage` 落 step→session_id,崩在中途也能接。
- **换代不 compact**(`556e615` / `350c877` / `7f39184` / `c7d910b`):上下文满了写交接换
  新会话。这四个 commit 是一条演进线,**每一个都在修前一个的坑**,细节见 §6.7。
- **打断续跑**(`bf3f022` / `239b37a` / `e657ce5` / `3123acb` / `75bb6d6`):Ctrl+C = 打断这一轮
  而不是杀进程;告诉模型"在飞的工具失败是打断副作用";信号处理器只置位不阻塞。
- **凭证 UX**(`772d05a` / `724425b`):多位置查找 + 首次引导配置 + 借 Claude Code token +
  开跑前探针验一次。
- **工具墙 + Web 工具**(`da41685` / `c87fce3`):`allowed_tools` 对动手工具排他;
  subagent 的 Web 工具必须并进会话级免审批清单(novel 卡死的真因)。
- **自动更新 + 行编辑**(`e0d7812`):后台非阻塞更新;cbreak 逐字符输入(中文退格、方向键)。
- **公开发布**(`4f3e5b2` / `4320506` / `7353af4`):一句话安装脚本 + Pages 文档站(挂 Pages
  域名,raw.githubusercontent 国内不通)。
- **docs 多语言重写**(`1432fc5` / `5ecd9c8` / `df429cb` 等):**用户自己在做,别碰。**

---

## 4. 验证状态(2026-09-09 亲手实跑,不是推断)

**九个离线测试全绿**(`.venv/bin/python tests/<name>.py`,退出码 0,不花钱):

| 测试 | 钉住什么 |
|---|---|
| `lineage_offline.py` | 同路径接续、判定者永远新会话、目录被拷走当没有 |
| `handoff_offline.py` | 换代:阈值/降级/熔断/**溢出只看这一轮 [14]** |
| `termsafe_offline.py` | 不超宽 / 不带危险转义 / ASCII 图标 / 真 pty 双进程不撕裂 / 锁不阻塞 |
| `input_offline.py` | 真 pty:退格删整个中文字、方向键、重绘不丢已输入 |
| `goal_offline.py` | 目标看守:三态判定、打回续跑、判不了问人 |
| `flow_offline.py` | Workflow.run 语义(when/gate/retries/reduce/on_fail) |
| `setup_offline.py` | 凭证:.env 优先级、Claude Code 回退只取 KNOWN、chmod 600 |
| `trial_offline.py` | 一键入口 + 工作台目录一致性(90 项) |
| `update_offline.py` | 自动更新:不阻塞/不换正在跑的自己/失败静默 + 节流 |

**Live 测试(花钱,这一轮没跑)** —— 需要真打 API 才算数的:
`wake_live.py`(跨进程 resume,实测 $0.235)、`handoff_live.py`(接班会话靠交接书接住,
$0.3–0.8)、`nesting_live.py`(subagent 再派 subagent)、`prelude_live.py`(subagent 能否
看见 session 级 `system_prompt.append` —— 和 #22 直接相关)、`resilience_live.py`(断网续跑)。
**改了换代 / 凭证 / 工具墙之后,该跑一次 `handoff_live.py` 复验。**

---

## 5. 代码地图(2026-09-09 核对过行数与锚点)

> 教训:第一版由 subagent 生成的地图**虚构了 `models.py`、错了一半行号**。下面这份
> 是逐个 grep 核对过的。改代码前还是自己 grep 一次锚点,行号会随编辑漂移。

### `flower/cli.py`(1482 行)—— 入口 + 终端渲染 + 输入
- `_OUT`(进程内锁)`:73`;`_TtyGuard`(跨进程 flock 写锁)`:90`,`WAIT = 0.25` `:120`,单例 `_TTY` `:177`
- `_sanitize`(只放行 SGR)`:222`;`_say`(唯一输出口)`:291`;`_cols`(CJK 按 2)`:256`
- `LineEditor`(行编辑状态机,可单测)`:320`;`Render`(事件渲染)`:489`
- 子命令 `go`/`run`/`once`/`setup`;`ensure_credentials` / `run_setup` 凭证引导

### `flower/core/`(14 个文件)
| 文件 | 行 | 承重内容(file:line)|
|---|---|---|
| `agent.py` | 275 | `default_window()` `:66`(**除 haiku 外一律判 1M** `:61,79-81`);`HandoffPolicy` `:85`(`room`/`at`/`warn_at`,`HEADROOM_FRACTION=0.25`,`max_generations=8`);`build_options`(prelude 拼进 `system_prompt.append` `:215`)|
| `runtime.py` | 637 | `Runtime` `:74`;run 循环 `:192`;**溢出判定 `errors[fresh:]`**(`fresh=` `:217`,判定 `:252`);换代分支 `:253-288`;`rescue` `:569`;`_persist` 并行追加 `:589` |
| `handoff.py` | 221 | `Handoff` `:88`;`is_overflow` `:71`(`_OVERFLOW` 正则**只认英文** `:60`);`degraded` `:204`;`HANDOFF_PROMPT` `:162` |
| `roles.py` | 548 | `WEB_TOOLS` `:33`;`worker` `:147`;`judge` `:356`;`coordinator` `:465`(把 subagent Web 工具并进会话级白名单 `:523`)|
| `workbench.py` | 169 | `Workbench` `:44`;`prompt_block()` `:138`(**注入 system prompt —— 这是 #22 的病灶**);索引 subagent 继承不到(`:19-25`)|
| `guard.py` | 285 | `whitelist_guard` `:43`(白名单=免审批,只拦主线程动手工具);`delegate_guard`(协调者不许自己动手);`spill_guard` / `index_guard` / `isolate_guard` |
| `lineage.py` | 117 | `Lineage` `:35`(`open`/`remember`/`archive`,原子写 `_flush` `:87`)|
| `env.py` | 218 | `load_dotenv` `:78`;`probe_credentials` `:126`;`_claude_code_env` `:56`(借 ~/.claude token,只取 KNOWN)|
| `brief.py` `:119` `Brief` / `goal.py` `:82` `Goal`+`Verdict`(三态) / `human.py` `:HumanChannel`(ask+inbox MCP 工具) / `resilience.py`(断网探针,错误不进上下文) / `events.py`(`normalize`) / `update.py` `:116` `maybe_update` ||

### `flower/workflow/`(4 个)
- `base.py`(295)`Step` `:71` / `Workflow` `:121`(run 主循环:gate/when/on_reject/血缘接续)
- `clarify.py`(123)前置确认 / `goal.py`(234)目标看守 / `starter.py`(223)三步起步流程 `确认→设目标→干活`

### `flower/stores/`(3 个)
- `prune.py`(282)`heal_orphans` `:95`(孤儿 tool_use 补配对,补而不删)/ `PruningSessionStore`(默认)
- `trim.py`(337)大 tool 结果落盘(spill),上下文只留路径 / `sqlite.py`(224)SessionStore

### `plugin/`(领域能力包,当前基本是空骨架)
`plugin.json`(name=`flower-domain`)+ `skills/example/SKILL.md`,`agents/`、`hooks/` 是空占位。
经 `PLUGIN_DIR`(`agent.py:26`)以 local plugin 挂载。

---

## 6. 地雷 —— 重新踩一次很贵

### 6.1 终端崩溃:是「多开 × 大块写入」相乘,不是任一单独成立(issue #21)
四次 Terminal.app 崩溃(2026-09-07 ×3,09-08 ×1),全是 Terminal 2.15/macOS 26.2 主线程
内存安全故障。**单开跑一整晚从不崩**。实测统一解释:`_TtyGuard.WAIT=0.25s` 抢不到锁就
放弃照写 → 慢终端下正常写入就阻塞超过 0.25s → 两个进程的字节流在任意位置交错 → 半个
UTF-8 / 腰斩的转义进 Terminal 解析器。**实测 `WAIT` 提到 2.0s 撕裂归零、吞吐不变**
(实际最长只等 0.81s)。分块写**修不了**(4KB 在慢终端下也会阻塞超时)。
→ 修法:`WAIT` 0.25→2.0,加一节**慢读端**双进程撕裂测试(现有 [7] 读端太快测不出)。
**平台风险**:tty 锁 / 逐字符输入 / SIGHUP 抢救这批修复全在 `cli.py`,靠 `fcntl`/
`termios`,**Windows 上会退化**(见 #20)。别以为"终端安全"已经全平台搞定 —— 只在 Unix 验过。

### 6.2 溢出判定的 latch(已修 `c7d910b`,别改回去)
`result.errors` 是整步累积、**从不清空**的。换代判定若拿整个列表判 `is_overflow`,
一条瞬时的 "Prompt is too long" 会 latch 住:这一步剩下每次失败都被判成溢出 →
`forced=True` → 直接抛 `_Overflow`、**连写交接那一轮都不跑** → 空交接换代。novel 那次
8 代 7 空,现场上下文才 41K/54K,离阈值差两个数量级。**修法**:只判这一轮新增的
`result.errors[fresh:]`(`fresh=len(result.errors)` 在 `_attempt` 前取快照)。
`handoff_offline.py [14]` 钉死。

### 6.3 换代那一轮会重新触发阈值(已修,`_writing_handoff` 豁免)
写交接是在越线之后、水位还挂在阈值之上时跑的。不豁免的话它第一条消息就又判"该换代",
交接一个字没写出来就被打断,每次降级。`_handoff_due()` 里的 `not self._writing_handoff`
不是小节 —— **漏掉它整套机制不工作**。离线测试抓不到(假 `_attempt` 没跑这条判据),
要靠 `handoff_live.py`。

### 6.4 subagent 的工具也必须进会话级 allowed_tools(已修 `c87fce3`)
`allowed_tools` 是**免审批清单,不是排他白名单**。subagent 定义里给了 `WebFetch`/
`WebSearch` 还不够 —— 它们也得在会话级 `allowed_tools` 里,否则每次卡权限确认,
看起来像"没有这个工具"。novel 那次 20+ 次 user-rejected、零产出就是这个。
`coordinator()` `:523` 现在会把 worker 的 Web 工具并进来。

### 6.5 省钱的杠杆是「少造新上下文」,不是「更聪明的缓存」(issue #22)
实测(真实探针 + novel 的 sessions.db):写缓存 $6.25/MTok 是读缓存 $0.50 的 **12.5 倍**。
subagent 前缀复用**已经在生效**(152 会话里 125 个第一次调用就命中缓存)——
`AgentDefinition.prompt` 是静态文本,前缀天然逐字节相同。**prompt 缓存在服务端,
落盘再加载这条路不存在。** 唯一的结构性浪费:`Workbench.prompt_block()` 把会变的
文件索引(路径+**大小**)塞进 system prompt,每落一个文件就作废整段前缀 —— 实测同一
请求贵 3.7 倍。修法:照 SDK 的 `exclude_dynamic_sections` 把索引搬进首条消息。约值 5%。

### 6.6 API/定价的事实必须实测,别凭记忆(这一轮的血泪)
见 §8。`total_cost_usd` 是**单次增量**不是会话累计(实测 resume 后 0.166→0.013);
每次 query 只有 1 条 ResultMessage;报的钱和 token 数严丝合缝。取证 subagent 一度
推断"cost 被累加了 91 倍",**是错的** —— 实测推翻。novel 账面 $3021 vs 实际 token
价 $234 的缺口目前**无定论**,更可能是 sessions.db 没记全,不是账面虚报。

### 6.7 窗口按模型名瞎猜,而且没有配置文件入口(issue #23,正在坑用户)
`default_window()` 除 haiku 外一律判 1M。用户网关(infini-ai)的 56 个模型里**根本没有
`claude-opus-5[1m]`**,回落到 200K 窗口的 `claude-opus-5`,而 flower 信了配置里的名字
判成 1M → 174K 溢出 → 走 §6.2 那条降级路。**窗口是网关的属性,和 BASE_URL 同类,
却只能靠 `--window` 命令行,没有配置文件键。** 修法三条:配置文件加 `FLOWER_WINDOW`;
**自校准**(第一次在 X 处收到 too-long 就记住 X,按 base_url+model 存);模型名不一致时警告。

### 6.8 工作台承重问题(旧地雷,仍在)
工作台索引走 session 级 `system_prompt.append`,**subagent 继承不到**(`workbench.py:19-25`)。
所以工作台的规矩必须由协调者**转述**给 subagent,不能指望它自己看到索引。
`prelude_live.py` 就是钉这条的。

### 6.9 孤儿 tool_use → 每次 resume 400(已修,`heal_orphans`)
在消息边界打断,会留下有 `tool_use` 却无配对 `tool_result` 的孤儿 → 之后每次 resume
都 API 400。`heal_orphans`(`prune.py:95`)给孤儿补一条合成 user 结果,**补而不删**。

### 6.9b spill_guard 会把「读落盘件」又落一次盘(已修,`reading_spill`)
大 tool 结果落盘、上下文只留路径;但模型用 Read 去读那个落盘件时,结果又超阈值、又被
落盘 —— "去读它"变成空话,自我重入。模型自己说过 "The spill read loops back on itself",
连试五种写法白烧七八轮。修法:`guard.py:155` 的 `reading_spill()` 认出"这是在读 spill
目录里的文件"就不再落盘。改 spill 逻辑时别把这条判断删了。

### 6.10 旧地雷仍成立(详见归档 §6)
- `--new` 才开新对话;默认同路径接续。
- 测试是独立脚本,**没有 pytest**;`*_offline.py` 免费,`*_live.py` 真花钱,跑前问。
- 注释用中文,每个不显然的决定写**为什么** + 实测数字("实测…")。
- `_OUT` 管进程内、`_TTY` 管跨进程,输出必须 `with _OUT, _TTY`。

---

## 7. Open issues backlog(共 15 个)

**这一轮开的(止损,按优先级)**:
- **#23** 窗口配置 + 自校准 —— 正在坑用户,最该先修(见 §6.7)
- **#21** 写锁 WAIT 0.25→2.0 + 慢读端测试 —— 一行改动,直接治崩溃(见 §6.1)
- **#22** 工作台索引搬出 system prompt —— 省约 5%(见 §6.5)
- **#24** 跑完给下一个工具(Claude Code/Codex)留一份 `CLAUDE.md`/`AGENTS.md` 交接
- **#20** Windows 支持(`help wanted`,等一台真机验)

**更早还开着的**:#1(三层执行结构)、#2(传输层透明重试)、#7(终端输出,已修大半)、
#11(`flower setup` 从 shell 到不了)、#12(全角 `？` 触发不了插话)、#13(凭证报错文案
和 `_claude_code_env` 实际行为矛盾)、#14(`once` 耗时/花费显示 0)、#15(plugin/ 不在
wheel 里,pip 装的静默失效)、#16(install.sh 的 PATH 提示在 macOS pip 路径上是错的)。

---

## 8. 我这一 session 犯的错(留给下一个,别重蹈)

1. **凭记忆断言 API/定价,错了三次**:先说"大块写入是崩溃主因"(被单开整夜不崩推翻)、
   再说"分块能修"(实测三种写法全撕裂)、跟着转述 subagent"cost 被累加 91 倍"(实测
   `total_cost_usd` 是增量)。**教训:API 行为一律实测,探针几毛钱,比猜便宜。**
2. **subagent 生成的代码地图第一版虚构了 `models.py` 和一半行号**,照抄就会写错 HANDOFF。
   **教训:subagent 报告要抽样核对,尤其 file:line 这种精确断言。**
3. 用户两次纠正我的方向("我觉得就是我们的错"、"应该并行无上限"),都对。
   **他对这套系统的直觉往往比我的第一反应准 —— 先认真验他的假设,别急着解释为什么不是。**

---

## 9. 起步(接手第一步)

```bash
cd ~/projects/flower
.venv/bin/python tests/handoff_offline.py    # 确认没被改坏,应全绿
git log --oneline -8                          # 看最近落了什么
gh issue list --repo ChenyuHeee/flower --state open
```

最紧的一件事仍是 §0:**用户有 flower 在 AI4S 跑,撞了 #6.7,救法是 `--window 200000`
同目录重启。** 别碰他的 `~/research/explore/AI4S/` 和 `docs/`。
