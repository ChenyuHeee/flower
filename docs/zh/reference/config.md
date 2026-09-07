# 配置

flower 没有配置文件格式,也没有配置子命令能真的跑到 —— 所有配置都是**环境变量**加
**`.env` 文件**,再加一批只能从 Python 侧给的策略对象。这一页把散在五个地方的东西收成一份:
每个变量、凭证按什么顺序找、`.env` 认什么语法、`setting_sources=[]` 到底隔绝了什么、
跑一次在磁盘上留下什么、会话存储三层各自丢掉什么、断网时怎么等。术语一律按[术语表](glossary.md)。

| 想知道 | 去 |
|---|---|
| flower 认哪些环境变量 | [环境变量完整表](#环境变量) |
| 我的 token 到底从哪来的 | [凭证查找优先级](#凭证查找优先级) |
| `.env` 里那行为什么没生效 | [`.env` 解析规则](#env-解析) |
| 换台机器要带什么 | [可移植性的代价](#可移植性) |
| `.flower/` 和 `runs/` 里都是什么 | [磁盘布局](#磁盘布局) |
| 哪些消息不会被喂回模型 | [会话存储三层](#会话存储) |
| 断网了它在等什么 | [断网韧性](#韧性) |

## 环境变量完整表 {#环境变量}

分四组:flower 直接读的凭证与端点、模型选择、路径查找、以及 flower **写给** agent 子进程的。
最后一组不用你设 —— 设了也会被覆盖。

### 凭证与端点 {#凭证变量}

| 变量 | 作用 | 默认 | 必需 | 出处 |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic 官方 key。有它就用 `x-api-key` 头发请求 | 无 | 与 `ANTHROPIC_AUTH_TOKEN` **二选一必需** | `env.py:28`、`:146`、`:157-158` |
| `ANTHROPIC_AUTH_TOKEN` | 网关签发的 token。没有 `ANTHROPIC_API_KEY` 时用 `authorization: Bearer` | 无 | 同上 | `env.py:28`、`:147`、`:159-160` |
| `ANTHROPIC_BASE_URL` | API 端点根地址。第三方网关填它自己的地址,**不带 `/v1`** —— 探针拼的是 `<BASE_URL>/v1/messages` | `https://api.anthropic.com` | 否 | `env.py:151`、`:162`、`:210`;`resilience.py:70` |

两个都没设(或者都是空字符串),`check_credentials()` 就返回那段四行的错误,`Runtime.__init__`
也会抛 `RuntimeError`(`env.py:184-194`;`runtime.py:156-158`)。

### 模型选择 {#模型变量}

flower 只读其中三个用来做自己的判断,其余是加载进来透传给 SDK 的。

| 变量 | 作用 | 默认 | 必需 | 出处 |
|---|---|---|---|---|
| `ANTHROPIC_MODEL` | 主模型名。同时决定[换代](glossary.md#换代)窗口的默认值:名字里带 `1m` 或不带 `haiku` → 100 万,带 `haiku` → 20 万 | 无(端侧决定) | 否 | `env.py:153`;`agent.py:77-81` |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | opus 档的模型映射。`ANTHROPIC_MODEL` 为空时,窗口判断退到它 | 无 | 否 | `agent.py:78`;`cli.py:1205` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | sonnet 档的模型映射。flower 自己不读,只负责加载和借用 | 无 | 否 | `env.py:34`;`cli.py:1206` |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | haiku 档的模型映射。**凭证探针优先用它** | 探针退到 `ANTHROPIC_MODEL`,再退到 `claude-3-5-haiku-20241022` | 否 | `env.py:152-153` |
| `CLAUDE_CODE_SUBAGENT_MODEL` | [subagent](glossary.md#subagent) 用哪个模型。flower 不解释它,由 SDK 消费 | 无 | 否 | `env.py:35`;`.env.example` |
| `CLAUDE_CODE_EFFORT_LEVEL` | 思考档位。同上,只加载不解释 | 无 | 否 | `env.py:35` |

`flower setup` 填了模型名的话,`ANTHROPIC_MODEL`、`ANTHROPIC_DEFAULT_OPUS_MODEL`、
`ANTHROPIC_DEFAULT_SONNET_MODEL` **三个一起写**(`cli.py:1204-1206`)。

### 路径与查找 {#路径变量}

| 变量 | 作用 | 默认 | 必需 | 出处 |
|---|---|---|---|---|
| `FLOWER_ENV` | 指定一个 `.env` 文件路径,排在所有其它文件**之前** | 无 | 否 | `env.py:48-49` |
| `XDG_CONFIG_HOME` | 决定全局凭证文件的位置 `$XDG_CONFIG_HOME/flower/.env` | `~/.config` | 否 | `env.py:41-42` |
| `HOME` | `Path.home()` 的来源,`~/.config` 和 `~/.claude` 两条路径都从它推 | 系统给 | 否 | `env.py:41`、`:67` |

### flower 写给 agent 子进程的 {#写出的变量}

这三个是 `CompactPolicy.env()` 生成后塞进 `ClaudeAgentOptions.env` 的(`agent.py:48-58`、`:241-245`),
控制 harness 内置的[压缩](glossary.md#压缩)。**你在 shell 里设它们没有意义** ——
真正生效的是 flower 传给子进程的那一份。

| 变量 | 作用 | 默认 | 必需 | 出处 |
|---|---|---|---|---|
| `DISABLE_AUTO_COMPACT` | `=1` 关掉自动压缩。[换代](glossary.md#换代)开着时**强制写入** —— 两套机制同时跑就分不清上下文回落是谁干的 | 换代默认开,所以实际恒为 `1` | 否(flower 写) | `agent.py:51`;`runtime.py:444-447` |
| `DISABLE_COMPACT` | `=1` 连 `/compact` 也一起关。只有 `CompactPolicy(mode="off")` 才写 | 不写 | 否(flower 写) | `agent.py:52-53` |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | 自动压缩的窗口(tokens)。只有 `CompactPolicy(window=N)` 才写 | 不写 | 否(flower 写) | `agent.py:56-57` |

### 容器包装器读的 {#容器变量}

这两个不是 flower 本体读的,是 `docker/flowerbox` 这个 shell 包装器读的。完整用法见[部署](deploy.md)。

| 变量 | 作用 | 默认 | 必需 | 出处 |
|---|---|---|---|---|
| `FLOWER_HOME` | 去哪找 `--env-file` 要用的那份 `.env` | 脚本自身位置的上一级目录 | 否 | `docker/flowerbox:12` |
| `FLOWER_IMAGE` | 用哪个镜像 | `flower-box` | 否 | `docker/flowerbox:13` |

**`.env` 里的键不限于上面这些。** 解析器把**所有** `k=v` 行都加载进 `os.environ`,不做白名单
(`env.py:30`、`:102-107`)。上面那 9 个凭证键组成的 `KNOWN` 只在两处起作用:借用 `~/.claude`
配置时的白名单(`env.py:72`),和 `-v` 启动时打印 `describe()` 的字段范围(`env.py:205`)。

## 凭证查找优先级 {#凭证查找优先级}

`load_dotenv()` 不传路径时,按下面的顺序把**所有存在的**文件依次读进来
(`env.py:45-53`、`:78-112`):

1. **进程环境变量** —— 永远最高。任何 `.env` 都盖不过已经 export 的值。(`env.py:91`)
2. **`$FLOWER_ENV` 指向的文件** —— 设了才有这一条。(`env.py:48-49`)
3. **`$PWD/.env`** —— 当前工作目录。`cd` 到哪个项目就近读哪个。(`env.py:50`)
4. **`${XDG_CONFIG_HOME:-~/.config}/flower/.env`** —— 每人一份的全局位置,`flower setup` 写的就是它。(`env.py:51`、`:39-42`)
5. **源码仓库根的 `.env`** —— `flower/core/env.py` 往上三层。只有从源码跑才存在;pip / pipx / uv 装出来的 flower 在 site-packages 里,没有这一条。(`env.py:52`)
6. **`~/.claude/settings.json`,然后 `~/.claude/settings.local.json` 的 `env` 块** —— 最后的回退,**只取 9 个凭证键**。(`env.py:56-75`、`:109-111`)

**哪个文件赢**:第 3 条(项目 `.env`)赢第 4 条(全局 `.env`),第 4 条赢第 5 条(仓库根 `.env`),
三者都赢第 6 条(Claude Code 的配置),而全部都赢不过第 1 条(进程环境)。

实现方式是“**已经有值的键不覆盖**”(`env.py:90-93`):排在前面的先把键占住,后面的只补空缺。
所以优先级是**按键算的,不是按文件算的** —— 项目 `.env` 里只写了 `ANTHROPIC_BASE_URL`,
token 照样可以来自全局那份。同名键第一次出现的值定终身。

第 6 条只在**自动查找**时启用。显式给了路径(`load_dotenv("/path/to/.env")`)就只读那一个文件,
不走任何回退(`env.py:86-87`、`:109`)。

### 第 6 条:借 Claude Code 的 token {#借用}

依次读 `~/.claude/settings.json` 和 `~/.claude/settings.local.json`,取 `data["env"]` 这个 dict,
从里面挑出这 9 个键(`env.py:31-36`、`:65-74`):

```text
ANTHROPIC_API_KEY   ANTHROPIC_AUTH_TOKEN   ANTHROPIC_BASE_URL
ANTHROPIC_MODEL     ANTHROPIC_DEFAULT_OPUS_MODEL    ANTHROPIC_DEFAULT_SONNET_MODEL
ANTHROPIC_DEFAULT_HAIKU_MODEL    CLAUDE_CODE_SUBAGENT_MODEL    CLAUDE_CODE_EFFORT_LEVEL
```

文件不存在、读不动、或者不是合法 JSON(`OSError` / `ValueError`),就返回空字典继续往下走 ——
**回退失效不该带走这次运行**(`env.py:62-63`、`:66-69`)。

代码里的立场是:借的只是“去哪找 token”,settings.json 里其它任何东西(权限规则、hook、
模型设置)一概不接管,所以这不违背 `setting_sources=[]` 的可移植承诺(`env.py:17-19`、`:59-61`)。
`install.sh:77` 把它当成一个特性宣传:本机配好 Claude Code 的人,连配置界面都不会看到。

!!! warning "产品内的错误文案和实际行为相反"
    完全找不到凭证时,flower 打印的错误最后一行是:

    ```text
    flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
    ```

    (`env.py:184-194`,那一句在 `:192`;同样的说法还出现在 `.env.example:2`、`env.py:3-4`、
    `agent.py:10-12`。)**以代码为准:它读。** `env.py:56-75` 加 `:109-111` 明确去读那两个文件,
    `install.sh:77` 还把这条当卖点。那句文案目前是误导性的 ——
    在一台配过 Claude Code 的机器上,你的 token 很可能就是从那里来的。

## `.env` 解析规则 {#env-解析}

解析规则短到可以背下来(`env.py:95-107`,13 行):逐行 `strip`,跳过空行、`#` 开头的行、
不含 `=` 的行;剩下的按**第一个** `=` 切成 key 和 value,两边各自 `strip`,value 再走一次
`.strip("'\"")` —— 首尾的单双引号一律剥掉,**不要求成对**。

**认这些写法**:

| 写法 | 结果 |
|---|---|
| `KEY=VALUE` | 正常 |
| `KEY = VALUE` | 正常 —— 等号两边的空格会被 strip 掉 |
| `KEY="VALUE"` / `KEY='VALUE'` | 正常 —— 首尾引号被剥掉 |
| `KEY=a=b` | value 是 `a=b` —— 按第一个 `=` 切,后面的等号原样留在值里 |
| `# 注释` | 整行跳过 |
| 空行 | 跳过 |

**不认这些**。写了不报错,只会静默得到一个意外的值:

| 写法 | 实际结果 |
|---|---|
| `export KEY=VALUE` | key 变成 `export KEY`,`KEY` 本身依然没有值 |
| `KEY=value # 说明` | value 是 `value # 说明` —— 行尾注释不剥离 |
| `KEY=$OTHER` | 字面量 `$OTHER`,不做变量插值 |
| 多行值(用引号跨行) | 逐行处理,第二行不含 `=`,会被整行跳过 |

**空值会把键占住**。`ANTHROPIC_AUTH_TOKEN=` 在高优先级的文件里出现,`take()` 会执行
`os.environ["ANTHROPIC_AUTH_TOKEN"] = ""`,于是后面的文件因为“键已存在”补不进来
(`env.py:90-93`);而 `check_credentials()` 判的是真值,空字符串照样算没配(`env.py:186`)。
**结果是既没有凭证、也拿不到回退。** 不想要某个键就整行删掉,别留一个空的。

## 可移植性的代价 {#可移植性}

`build_options()` 里那一行是全部机关(`agent.py:207`):

```python
"setting_sources": [] if portable else ["project"],
```

`portable=True` 是 `Runtime` 的默认值,**命令行没有开关能关掉它** —— 要关只能走 Python API
写 `Runtime(portable=False)`,那会变成 `["project"]`,即读项目的 `.claude/`。

### 被隔绝的东西

| 被隔绝的 | 后果 |
|---|---|
| 宿主机 `~/.claude/` 的设置 | 那里的权限规则、hook、模型设置一概不生效。**凭证是唯一例外**,见[借用](#借用) |
| 项目的 `.claude/` | 同上,`portable=False` 时才读 |

领域能力不走这条路 —— 它随仓库分发,通过 `plugins=[{"type": "local", "path": PLUGIN_DIR}]` 加载
(`agent.py:26`、`:210-212`),见[部署](deploy.md)。领域指令则是**叠加**在 Claude Code 原生系统
提示词之后,不是替换(`agent.py:198-202`),所以专业化不以损失通用能力为代价。

### 换台机器要带什么

- **凭证:一个文件**。`~/.config/flower/.env` 拷过去就行,或者在新机器上重新配一次。
  不带的话什么都跑不起来 —— 不会有任何东西被自动继承。
- **接续状态:整个目录**。`runs/`(会话库、清单、血缘)和 `.flower/`(工作台)。
- **但路径要一致**。`lineage.json` 里存了工作区的绝对路径,对不上就当没有,静默退回新会话,
  **不报错**(`lineage.py:65-66`)。原因是 SDK 的 `project_key` 从工作区路径推导
  (`/`、`_`、`.` 全换成 `-`,`runtime.py:40-41`),目录换了位置,旧的 `session_id` 就查不到了。

## 磁盘布局 {#磁盘布局}

跑一次 flower 会写两棵树:`<run_dir>/` 放账目和会话,`<workspace>/.flower/` 放[工作台](glossary.md#工作台)。
两者默认都在当前目录下,但**它们的基准不同**。

!!! warning "`runs/` 跟着当前目录走,不跟着 `-w`"
    `-r/--run-dir` 默认 `"runs"`,而 `Runtime` 对它做的是 `Path(run_dir).resolve()`
    (`runtime.py:93-94`)—— 相对**当前工作目录**,不是相对 `-w` 指定的工作区。
    在 `~` 下跑 `flower -w /path/to/proj`,会话库会落在 `~/runs/`,不在项目里。

### `<run_dir>/` —— 默认 `./runs/` {#run-dir}

```text
runs/
  sessions.db        SQLite,全量 transcript(含每个 subagent 自己那条)
  manifest.json      运行清单:每一步的 session_id / 花费 / 重试 / 失败原因,跨进程累积
  lineage.json       血缘:步骤名 → session_id,同一个目录再跑一次靠它接上
  aside/             旁路问答的独立 Runtime,自己的 sessions.db + manifest.json
  workbench/         仅当走 run / once 路径且给了 -W
```

| 路径 | 内容 | 出处 |
|---|---|---|
| `runs/sessions.db` | 全量 transcript。写它的是 `PruningSessionStore`,三层策略见[下文](#会话存储) | `runtime.py:109-112` |
| `runs/manifest.json` | JSON 数组,**跨进程累积**的[运行清单](glossary.md#运行清单)。字段见下表 | `runtime.py:532-533`、`:564-586` |
| `runs/lineage.json` | `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`。先写 `.tmp` 再 `replace`,原子替换 | `lineage.py:31`、`:87-97` |
| `runs/aside/` | [旁路顾问](glossary.md#旁路顾问)的独立 Runtime。**花费和血缘不混进主清单** | `cli.py:632-634` |
| `runs/workbench/` | `Runtime(workbench=True)` 的默认工作台位置,在工作区之外。`go` 路径不用它 | `runtime.py:148-151` |

`manifest.json` 每一行是 `asdict(StepResult)` 加两个补丁(`runtime.py:44-71`、`:579-582`):

| 字段 | 类型 | 含义 |
|---|---|---|
| `step` | `str` | 步骤名。四种形态:`<名>`、`<名>#round<N>`(被打回重做)、`<名>#retry<N>`(普通重试)、`<名>·判定#<N>`([判定者](glossary.md#判定者)) |
| `session_id` | `str \| None` | 这一步最后活着的那条[会话](glossary.md#会话) |
| `ok` | `bool` | 成没成 |
| `cost_usd` | `float` | 这一步花了多少 |
| `num_turns` | `int` | 跑了几轮 |
| `text` | `str` | 这一步的最终回话 |
| `error` | `str \| None` | 失败原因。被 SIGHUP / SIGTERM 杀掉时是 `killed-by-signal`(`runtime.py:556-558`) |
| `started_at` / `ended_at` | `float` | epoch 秒 |
| `attempts` | `int` | 实际尝试次数。`>1` 说明重试过 |
| `errors` | `list[str]` | 历次失败原因。**只在这里,模型看不到** |
| `resumed` | `bool` | 是否靠 resume 从中断处接上,而不是重头跑 |
| `retired` | `list[str]` | 这一步[换代](glossary.md#换代)时烧掉的 session_id,按顺序 |
| `context` | `int` | 最后一轮[主线程](glossary.md#主线程)实际看到的上下文规模 |
| `duration_s` | `float` | 手工补的 —— 它是 `@property`,`asdict()` 收不到 |
| `run` | `str` | 本进程标记 `YYYYmmdd-HHMMSS-<6 位 hex>`。**必须每实例唯一** |

写盘策略是**追加不覆盖**:每次落盘先重读一遍文件,把 `run` 等于自己的行换成最新的,
别人的行原样留着(`runtime.py:564-586`)。所以同一个目录并行跑多个 flower,账不会互相冲掉。

`runs/` 里的东西是纯数据,随时可以用 sqlite3 或
[`tools/analyze_run.py`](https://github.com/ChenyuHeee/flower/blob/main/tools/analyze_run.py)
离线翻。

### `<workspace>/.flower/` —— 工作台 {#工作台目录}

```text
.flower/
  INDEX.md      自动生成的索引,注入主 agent 的 system prompt
  scripts/      要跑第二次的脚本。首行 `# desc: 一句话` 会出现在索引里
  artifacts/    超过 2000 字符的长产出:报告、数据、日志
  notes/        跨步骤的决策记录
  spill/        落盘的大工具结果,文件名 = 内容 sha256 前 16 位 + `.txt`
```

三个子目录加索引由 `Workbench` 建(`workbench.py:73-92`)。`INDEX.md` 走会话级的
`system_prompt.append`,**subagent 继承不到** —— 所以“长产出写 `artifacts/`”这条规矩必须由
[协调者](glossary.md#协调者)在[任务书](glossary.md#任务书)里转述,那是唯一通道。

`go` 路径在 `notes/` 下固定生成这些:

| 文件 | 内容 | 出处 |
|---|---|---|
| `notes/需求.md` | 冻结的[需求确认书](glossary.md#需求确认书),四段:目标 / 验收标准 / 边界 / 未知与假设 | `brief.py:44-45`;`clarify.py:105` |
| `notes/目标.md` | 冻结的两段:目标 / 判定清单 | `workflow/goal.py:124` |
| `notes/问答记录.md` | 全部问答的追加记录,含“人主动说”的收件箱条目。**不进上下文,只作留档** | `human.py:421-433` |
| `notes/交接-<步骤名>.md` | [交接书](glossary.md#交接书)。上一代收进 `notes/archive/交接/<步骤名>-<时间戳>.md` | `runtime.py:388-403` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | `--new` / `/new` 归档的 `lineage.json` + `需求.md` + `目标.md`(**移动,不删除**) | `lineage.py:100-117` |

**`--isolate` 时工作台移到仓库外**:`<workspace 的父目录>/.flower-<workspace 名>/`
(`starter.py:47-55`)。worktree 是每个 agent 的私有副本,工作台是跨 agent 的共享层,
共享的东西不能放进私有围栏里。此时给模型的路径是绝对路径(`workbench.py:69-71`、`:142-145`)。

**`spill/` 有两个写入者,落点算法不同**:

| 谁写 | 什么时候 | 写到哪 | 阈值 |
|---|---|---|---|
| `spill_guard`(`PostToolUse` hook) | 工具结果进模型**之前** | `<工作台 root>/spill/`(`guard.py:130`) | `spill_threshold`,默认 4000 字符 |
| `TrimPolicy`(`load` 时) | resume 前重放历史时 | `<workspace>/.flower/spill/` —— 相对工作区的固定字符串(`trim.py:49`、`:303`) | `min_chars`,默认 2000 字符 |

默认布局下这是同一个目录。但工作台被挪走时(`-W` 让它落到 `runs/workbench/`,或者 `--isolate`
让它落到仓库外)两者就分开了 —— `TrimPolicy` 那一份始终在工作区里,因为 agent 的 `Read`
必须够得到它。

`spill_guard` 换上去的不是一行,是一行指针加**开头 400 字符**(`guard.py:132-140`)。
读落盘文件本身的调用会被放行,不然“需要全文用 Read 读它”是句空话 —— 读回来又超阈值,又被落盘,
无限循环(`guard.py:155-170`)。

### `sessions.db` 的表结构 {#sessions-db}

三张表,建表语句在 `stores/sqlite.py:27-51`:

```sql
CREATE TABLE entries (
    store_key TEXT NOT NULL,
    seq       INTEGER NOT NULL,
    uid       TEXT,
    payload   TEXT NOT NULL,
    PRIMARY KEY (store_key, seq)
);
CREATE UNIQUE INDEX entries_uid
    ON entries(store_key, uid) WHERE uid IS NOT NULL;
CREATE TABLE meta (
    store_key TEXT PRIMARY KEY,
    mtime     INTEGER NOT NULL,
    next_seq  INTEGER NOT NULL
);
CREATE TABLE summaries (
    project_key TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    mtime       INTEGER NOT NULL,
    data        TEXT NOT NULL,
    PRIMARY KEY (project_key, session_id)
);
```

| 表 | 一行是什么 | 要点 |
|---|---|---|
| `entries` | transcript 里的一条,`payload` 是原始 JSON | `uid` 就是条目的 `uuid`,做**幂等键**:失败批次会被重试 3 次,重放不能产生重复行。没有 `uuid` 的条目(标题、标签、模式标记)不去重,所以唯一索引带 `WHERE uid IS NOT NULL` |
| `meta` | 一条会话的游标 | `next_seq` 是下一个序号,`mtime` 是毫秒时间戳且**严格单调**(`sqlite.py:72-79`)—— `list_sessions` 和 summary 共用这个时钟,不单调会让 SDK 的判新旧走错快路径 |
| `summaries` | 一条主会话的摘要 sidecar | **只有主 transcript 参与**,subagent 的不算(`sqlite.py:122-123`) |

`store_key` 的构造(`sqlite.py:54-58`):`<project_key>/<session_id>`,subagent 再接一段
`subpath`。`project_key` 由 SDK 从工作区路径推导 —— `/`、`_`、`.` 全换成 `-`。

拿真实样本看一眼([`human-test/HT002/runs/sessions.db`](https://github.com/ChenyuHeee/flower/blob/main/human-test/HT002/runs/sessions.db)):

```bash
sqlite3 runs/sessions.db "select store_key, next_seq from meta;"
```

```text
-Users-hechenyu-explore-test-ide/601c8c91-6c4b-4525-8a5f-295b99bf9515|37
-Users-hechenyu-explore-test-ide/47395075-bec7-466e-80cd-f4d60b360235|80
-Users-hechenyu-explore-test-ide/47395075-…/subagents/agent-a99a6ce30a5471f44|104
```

那一份是 956 条 `entries`、10 条 `meta`、4 条 `summaries` —— 10 条会话里 4 条是主 transcript,
6 条是 subagent 的,而 `summaries` 恰好等于主 transcript 的数目。

## 会话存储三层 {#会话存储}

!!! note "三层是继承链,不是可选组合"
    `PruningSessionStore` 继承 `TrimmingSessionStore` 继承 `SqliteSessionStore`。
    `Runtime` **永远**构造最外层那个(`runtime.py:109-112`),构造参数里没有换后端的入口。
    “关掉某一层”的办法是把它的策略对象 `enabled` 设成 `False`,不是换类。

`append`(写)永远是全量落盘,一个字不改。三层只影响 `load`(读回去喂给模型的那一份)。
`load` 的实际顺序是:

```text
SqliteSessionStore.load     从 entries 表按 seq 读出全部
  → TrimmingSessionStore.expire()   时效性 Bash 结果 → 换成"已过期"
  → TrimmingSessionStore.trim()     旧的大 tool_result → 落盘 + 换成指针
    → PruningSessionStore.prune()   合成错误消息 / 旧的被拒调用 → 整条摘掉并重接链
```

| 层 | 类 | 丢什么 | 判据 |
|---|---|---|---|
| 1 | `SqliteSessionStore` | 什么都不丢 | —— |
| 2 | `TrimmingSessionStore` | 大的工具结果正文、过期的一次性命令结果 | 体积 + 时效 |
| 3 | `PruningSessionStore` | 断线残渣、旧的被拒调用 | 是不是错误 |

第 2 层是[裁剪](glossary.md#裁剪),第 3 层是[剪除](glossary.md#剪除) ——
**裁剪按体积和价值丢,剪除按“是不是错误”丢**,别混。完整签名见 [Python API](api.md)。

### `SqliteSessionStore` —— 地基 {#sqlite-store}

```python
SqliteSessionStore(path: str | Path)
```

零外部依赖的 SQLite 实现。要换 Postgres / S3 / Redis,实现同一个协议即可,SDK 自带一致性测试
套件 `claude_agent_sdk.testing.session_store_conformance` 可以直接验证(`sqlite.py:1-8`)。

除协议方法外,还有三个**同步**查询,给 flower 自己用:

| 方法 | 返回 | 用途 |
|---|---|---|
| `projects()` | `list[str]` | 库里实际存在的 `project_key`。SDK 由 cwd 推导它,查询前用这个确认,别猜 |
| `has_session(project_key, session_id)` | `bool` | 只查 `meta` 一行,不读 payload。[接续](glossary.md#接续)开跑前先查 —— resume 一个不存在的会话会在子进程起来之后才炸,那时候钱和时间都花了 |
| `last_context(project_key, session_id, scan=60)` | `int` | 这条会话最后一轮看到多大上下文。只倒着扫最后 60 条。`input_tokens` 加两个 `cache_*` 都算 —— 只看前者,缓存命中时接近 0,会严重低估 |

### `TrimmingSessionStore` + `TrimPolicy` / `EphemeralPolicy` {#trimming-store}

```python
TrimmingSessionStore(path, workspace, policy: TrimPolicy | None = None,
                     ephemeral: EphemeralPolicy | None = None)
```

两条正交的规则。`TrimPolicy` 管**体积**:

| 参数 | 类型 | 默认 | 语义 |
|---|---|---|---|
| `keep_recent` | `int` | `20` | 最近 N 个 `tool_result` 保留原文 —— 正在用的上下文不该被裁 |
| `min_chars` | `int` | `2000` | 短于这个不裁。换成指针反而更费 token |
| `spill_dirname` | `str` | `".flower/spill"` | 归档目录,**相对 workspace**。必须在工作区内,否则 agent 的 `Read` 够不到 |
| `enabled` | `bool` | `True` | `Runtime(trim=False)`(默认)时是 `False` |

被裁的正文写成 `<sha256 前 16 位>.txt`,原位置换成
`[工具结果已归档:N 字符。完整内容在 <路径>,需要时用 Read 读取]`(`trim.py:54-57`、`:308-317`)。

`EphemeralPolicy` 管**时效**:`git status`、`ls`、`ps` 这类结果很短,按体积永远轮不到裁,
但它们的正确性随时间衰减 —— 20 轮前那份 `git status` 不是“没用”,是**会误导**。

| 参数 | 类型 | 默认 | 语义 |
|---|---|---|---|
| `enabled` | `bool` | `True` | `Runtime(ephemeral=…)` 转换而来,**默认开** |
| `keep_recent` | `int` | `6` | 最近 N 条保留原文。比 `TrimPolicy` 的 20 小得多 —— 这类东西“最近”的窗口本来就短 |
| `max_chars` | `int` | `2000` | 超过就交给 `TrimPolicy` 落盘归档,不走这条路 |
| `text` | `str` | `"[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"` | 替换文案 |

只作用于 **Bash** 工具的结果,而且命令要匹配 `EPHEMERAL_CMD`。`Read` 不在此列:文件内容不会因为
时间流逝失真到误导的程度,而且它可能正是模型推理的依据(`trim.py:153-160`)。过期的内容
**不落盘** —— 归档一份过期的 `git status` 没有意义,重跑一次就有了。

判断函数是 `is_ephemeral(cmd)`,它**同时是还给协调者的权限清单**:`delegate_guard(allow_glance=True)`
用的是同一个函数(`trim.py:63-68`、`:128-150`)。两个集合必须永远相等 ——
放行了但不剪枝,过期的 `git status` 就永久占着上下文;剪枝了但不放行,主 agent 为一条 `ls`
派个 subagent,4.3k 启动成本换几十字符。往白名单里加一条命令,等于同时说了这两句话。

**什么时候用哪个**:

- 只想让断线残渣不进上下文 → 什么都不用做,`Runtime` 默认就是 `PruningSessionStore`。
  `trim=False` 只是不裁大结果,摘除照做。
- 长跑、工具输出很大 → `trim=True`。`go` 路径的 CLI 默认已经开着,用 `--no-trim` 反向关。
- [协调者](glossary.md#协调者)开了 `glance=True` → `ephemeral` 必须保持开着,理由见上一段。

### `PruningSessionStore` + `PrunePolicy` {#pruning-store}

```python
PruningSessionStore(path, workspace, policy: TrimPolicy | None = None,
                    prune: PrunePolicy | None = None,
                    ephemeral: EphemeralPolicy | None = None)
```

| 参数 | 类型 | 默认 | 语义 |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | 摘掉 `isApiErrorMessage=true` 或 `message.model == "<synthetic>"` 的合成消息 |
| `neutralize_interrupts` | `bool` | `True` | `[Request interrupted …]` 的 `tool_result` **换正文,不摘块** |
| `interrupt_text` | `str` | `"[上一轮在此处被中断,该工具结果未产生]"` | 上一条的替换文案 |
| `keep_denials` | `int` | `1` | 保留最近 N 次被 permission hook 拒掉的工具调用,更早的**连调用带结果一起**摘掉 |

`keep_denials` 是唯一透传到这一层的 `Runtime` 构造参数(`Runtime(keep_denials=N)`)。
默认 1 而不是 0 的理由:最新那次拒绝是有效信号,能防止模型在同一轮里反复重试同一条被拦的命令。
**别调大** —— 被拒的调用从来没执行过,结果里没有任何信息,实测一次占 273 字符
(93 字拒绝语加 180 字死命令原文),而且它**会误导**:实测协调者读到几条“不直接使用 Bash”之后,
连放行的 `git status` 都不再尝试,直接说“Bash 被限制了,派个 agent 去看”(`prune.py:135-148`)。

三条结构性红线,违反了 API 直接报错:

1. **`tool_result` 块本身必须在**,只能换 `content`。少一个就是 “Missing Tool Result Block”
   (`trim.py:20-22`;`prune.py:79-92`)。
2. **`isCompactSummary` / `isMeta` 条目不能动** —— 那是被压掉的那段历史唯一的存在形式
   (`trim.py:179-181`)。
3. **摘掉一条就必须把它的孩子接到它的父亲上**。transcript 是 `parentUuid` 单链,harness 从叶子
   往回走,链断在哪里前面的历史就全丢(`prune.py:95-122`)。所以 `relink()` 要拿到**包含**待摘
   条目的完整列表,过滤由它自己做。

**SQLite 里的原文一个字都不改** —— 三层只影响“喂回模型的那一份”(`trim.py:18`;`prune.py:8`)。

## 断网韧性 {#韧性}

长程 workflow 一跑就是几小时,网络必然会断一次。默认行为很糟:断线那一刻 harness 往 transcript
里塞一条合成 assistant 消息(`model="<synthetic>"`、`isApiErrorMessage=true`),正文是
`API Error: Can't reach the API server …`;它成了会话的叶子,之后 resume 就被当成“模型上一句说的话”
喂回去,模型以为自己在讨论网络故障;它还会混进 `StepResult.text`,顺着 workflow 传给下一步的
prompt(`resilience.py:1-22`)。

[韧性](glossary.md#韧性)这一层做三件事,缺一不可:探针、续跑而不是重来、错误不进上下文。

### `Resilience` 参数 {#resilience}

| 参数 | 类型 | 默认 | 语义 |
|---|---|---|---|
| `enabled` | `bool` | `True` | `Runtime(resilience=…)` 转换而来 |
| `max_attempts` | `int` | `6` | 一个[步骤](glossary.md#步骤)最多尝试几次,**含首次** |
| `base_delay` | `float` | `4.0` | 指数退避起点,秒 |
| `max_delay` | `float` | `120.0` | 退避上限,秒 |
| `probe_timeout` | `float` | `5.0` | 单次探针超时,秒 |
| `probe_interval` | `float` | `15.0` | 断网时多久探一次,秒 |
| `max_offline_wait` | `float` | `3600.0` | 断网最多等多久。默认 1 小时 —— 长过这个通常不是抖动,是真出事了 |
| `retry_unknown` | `bool` | `True` | 分类不出来的错误也重试。多数未知错误是瞬时的,而致命错误已经被单独挡住了 |
| `resume_prompt` | `str` | `"上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,从中断处接着做,不要重头来过。"` | 续跑时对模型说的话 |

退避公式(`resilience.py:119-121`):

```python
min(base_delay * 2 ** (attempt - 1), max_delay) * (0.75 + random() * 0.5)
```

即 `±25%` 抖动,避免网络恢复的瞬间一堆进程一起冲上去。按默认值:第 1 次退避 4 秒(实际 3~5),
第 2 次 8 秒(6~10),第 5 次起封顶 120 秒(90~150)。

### 探针策略 {#探针}

- **探的是 `ANTHROPIC_BASE_URL` 的 host:port**,不是 `api.anthropic.com`(`resilience.py:67-72`)。
  用自建网关时,后者通说明不了前者通。
- **只做 DNS 加 TCP 握手**:`getaddrinfo` 然后 `connect_tcp` 然后立刻关掉。不发 HTTP、
  不带凭证、不花钱(`resilience.py:75-85`)。探针必须免费,否则“断网时每 15 秒探一次”
  本身就成了故障。
- 任何失败都算不可达 —— 不区分是 DNS 挂了还是 TCP 拒绝。
- `wait_online()` 挂在那里等:通了返回 `True`,等满 `max_offline_wait` 返回 `False`。
  第一次不可达时通知一行 `<host>:<port> 不可达,等待恢复(最多 60 分钟)`,恢复时再通知一行
  `<host>:<port> 恢复,继续`,**中间不刷屏**(`resilience.py:126-140`)。

开跑前那次凭证探针是另一回事:它真打一次 `POST <BASE_URL>/v1/messages`,`max_tokens=16`,
默认超时 20 秒(`env.py:126-181`)。`max_tokens` **别设成 1** —— 实测强制思维链的模型连思考都
放不下,服务端挣扎到 30 秒才返回;设 16 只要 3.6 秒(`env.py:120-123`)。

### 错误分类 {#错误分类}

`classify(text)` 返回三种之一。**先判致命**:401 之类的文本里常常也带着 “connection” 这种词,
顺序反了会死等(`resilience.py:53-64`)。

| 分类 | 命中什么(正则见 `resilience.py:37-50`) | 行为 |
|---|---|---|
| `fatal` | `400` `401` `403` `404`、`invalid api key`、`authentication`、`unauthorized`、`permission denied`、`invalid_request`、`credit balance`、`quota exceeded`、`budget`、`max_turns`、`CLINotFound` | 立刻停,不重试。重试多少次结果都一样,而且每次都要钱 |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`、`socket hang up`、`fetch failed`、`Can't reach the API server`、`429` `500` `502` `503` `504` `529`、`overloaded`、`rate limit`、`timeout`、`service unavailable` | 等网络回来,然后 resume 续跑 |
| `unknown` | 都不匹配 | `retry_unknown=True`(默认)时也重试 |

区分可重试与不可重试是这一层的核心:**网络抖动该等,凭证错该立刻停** ——
断网时死等是对的,key 写错了死等就是烧时间。

### 什么被挡在上下文外面 {#错误不进上下文}

1. **合成错误消息**。`PruningSessionStore` 在 `load` 时把它整条摘掉并重接 `parentUuid`
   (`prune.py:27-32`、`:191-195`)。**SQLite 里原样保留**,只是不喂回去。
2. **事件流里它是 `kind="error"` 而不是 `"text"`**,所以不进 `StepResult.text`,
   也就不会顺着 workflow 传给下一步的 prompt(`resilience.py:17-18`)。
3. **`resume_prompt` 有意不含任何错误细节**。模型需要知道“被打断了、接着做”,不需要知道是
   `ENOTFOUND` 还是 `503`。**那属于日志,不属于上下文**(`resilience.py:112-113`)。
   日志去 `manifest.json` 的 `errors` 字段看。

续跑而不是重来:失败发生时 `session_id` 已经拿到了,用 resume 从中断处接上,之前的花费不白费。

## 相关 {#相关}

- [命令行](cli.md) —— 每个开关怎么映射到这一页的配置。
- [Python API](api.md) —— `Runtime`、三个 store、`Resilience` 的完整签名。
- [部署](deploy.md) —— 容器里跑、用 plugin 分发领域能力。
- [术语表](glossary.md) —— 这一页用到的每个词的准确含义。
