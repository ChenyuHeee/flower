# 常见问题与排错

出问题的时候,人不知道是哪个模块坏了 —— 只知道自己看见了什么。所以这一页按**你观察到的现象**
分组,不按子系统分。

每条的结构一样:**症状**(你实际看到的东西)→ **原因** → **怎么办**。

其中五条是**已知缺陷**,不是设计如此。这些条目会直接说明是 bug、给出 issue 链接和绕法 ——
不会把它们说成是有意为之。

## 装不上 / 跑不起来 {#装不上}

装的完整流程见 [install.md](../getting-started/install.md#一句话安装)。这一节只收"装完了,
但命令跑不起来"的几种。

### Python 版本低于 3.10 {#python-版本}

**症状**:安装过程中蹦出语法错误,或者 pip 直接说找不到满足条件的版本。

**原因**:flower 要求 Python ≥ 3.10。唯一的运行依赖是 `claude-agent-sdk`,原生二进制在它的
wheel 里 —— 所以装不上多半是解释器版本的问题,不是网络。

**怎么办**:先确认要装进哪个解释器。

```bash
python3 --version
```

低于 3.10 就换一个再装。系统自带的 `python3` 常常不是你终端里 `python` 指向的那个,
装之前对一次版本比装完再排查便宜(见 [install.md](../getting-started/install.md#装之前确认-python))。

### 装完了,`flower: command not found` {#command-not-found}

**症状**:

```text
zsh: command not found: flower
```

**原因**:包装上了,但生成的可执行脚本所在的目录不在 `PATH` 里。这和"没装上"是两回事 ——
`python3 -c "import flower"` 不报错就说明包是好的。

**怎么办**:`flower` 脚本的 shebang 是绝对路径,所以软链一份到已经在 `PATH` 里的目录就够,
不需要 source 任何东西。

```bash
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

### macOS:照 `install.sh` 的提示加了 PATH,还是 command not found {#macos-path}

!!! warning "已知问题([issue #16](https://github.com/ChenyuHeee/flower/issues/16))"

    这条建议恰好在需要它的那台机器上失效。

**症状**:在 macOS 上跑完 `install.sh`,照它最后那句提示把 `~/.local/bin` 加进 `PATH`,
重开终端,`flower` 仍然 command not found。

**原因**:走到 pip 兜底那条路时,macOS 的 pip 把可执行脚本装进 `~/Library/Python/3.X/bin`,
而 `install.sh` 提示要加的是 `~/.local/bin`。两个目录对不上,提示照做也没用。

**怎么办**:不要猜目录,问解释器要。

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))"
```

把打印出来的那个目录加进 `PATH`,或者从它软链一份到 `~/.local/bin`:

```bash
ln -sf "$(python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))")/flower" ~/.local/bin/flower
```

### uv / pipx / pip 装出来的不是同一个 flower {#三种装法}

**症状**:`flower` 能跑,但改了源码不生效;或者升级完还是旧版本;或者同一台机器上两个终端行为不一样。

**原因**:三种装法把包和可执行脚本放在不同地方,`PATH` 里先命中哪个就跑哪个。

??? note "三种装法落在哪"

    | 装法 | 可执行脚本 | 什么时候用 |
    |---|---|---|
    | `python3 -m venv .venv` + `pip install -e .` | `.venv/bin/flower` | 要改源码。改完立刻生效 |
    | `uv tool install` / `pipx install` | `~/.local/bin/flower` | 只用不改,要一个隔离的环境 |
    | `pip install --user` | Linux `~/.local/bin`,macOS `~/Library/Python/3.X/bin` | 兜底。目录见上一条 |

**怎么办**:先确认现在跑的是哪一个,再决定改哪一份。

```bash
which -a flower                      # 列出 PATH 上所有同名的
head -1 "$(which flower)"            # shebang 指向哪个解释器,包就在那个环境里
```

要改源码就用 venv + `-e .`,别和 `uv` / `pipx` 装的那份共存 —— 共存时排查成本远高于重装一次
(见 [install.md](../getting-started/install.md#从源码装))。

## 凭证与网关 {#凭证}

### `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN` {#缺少凭证}

**症状**:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN
```

**原因**:flower 用 `setting_sources=[]` 隔绝了宿主机配置,凭证必须自带。完整的查找顺序见
[config.md](config.md#凭证查找优先级)。

**怎么办**:写进仓库根的 `.env`,或者写进进程环境。

```bash
cp .env.example .env        # 填 ANTHROPIC_AUTH_TOKEN 或 ANTHROPIC_API_KEY
```

`.env` 已被 gitignore。容器里的写法见 [deploy.md](deploy.md#凭证)。

### 它说"flower 不读 `~/.claude/settings.json`" —— 这句话是错的 {#settings-json}

**症状**:凭证没配好时,`env.py:192` 打出一句:

```text
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价
```

**原因**:这句话和代码不符。`env.py:56-75` **确实会读** `~/.claude/settings.json`,只取其中的
凭证字段,作为最后一级兜底 —— `install.sh` 宣传的也正是这一条。这句话只在兜底已经找空之后
才打印,所以它不会让任何东西失败;但它会让人得出"flower 用不了我 Claude Code 那份 token"的
结论,而那是错的。已记在 [issue #13](https://github.com/ChenyuHeee/flower/issues/13)。

**怎么办**:本机装过 Claude Code 的,不必重新申请凭证,兜底会自己捡起来
(见 [install.md](../getting-started/install.md#本机装过-claude-code-的话可能一个问题都不问))。
真的看到了这句话,说明那个文件里也没有可用的凭证字段 —— 按上一条写 `.env`。

### 不确定生效的到底是哪套凭证和端点 {#生效值}

**症状**:明明改了 `.env`,请求还是打到旧网关;或者说不清现在用的是哪个模型。

**原因**:凭证和端点有多个来源(进程环境、`.env`、兜底),谁赢了不看配置文件,看运行时。

**怎么办**:带 `-v` 起一次。启动时会打印 `describe()`:生效的 `BASE_URL` 与模型映射,token 打码。

```bash
flower -v
```

开关全表见 [cli.md](cli.md#全局开关),变量全表见 [config.md](config.md#环境变量)。

### `.env` 里留了 `KEY=`,下游就再也填不上了 {#空值占位}

**症状**:进程环境里 export 了 token,`.env` 里也有 `ANTHROPIC_AUTH_TOKEN=` 这一行,
仍然报"缺少凭证"。

**原因**:空值也是一次赋值。高优先级来源里的 `KEY=` 把这个键**占住**了,低优先级来源不会再
往里填;而 `check_credentials()` 判的是"值非空",于是照样报缺失。"占位"和"缺失"是两件事,
现象却一模一样 —— 这是这一类问题最难自己看出来的地方。

**怎么办**:把整行删掉,不要留空值。

```bash
grep -n '^[A-Za-z_][A-Za-z0-9_]*=$' .env     # 列出所有空值行
```

删完再用 `-v` 确认一次生效值。解析规则见 [config.md](config.md#env-解析)。

### 第三方网关:连上了,但第一轮就失败 {#网关}

**症状**:401 / 403;或者报模型名不存在;或者一开局就换代,还报"启动地板"。

**原因**:三类配错,现象各不相同。

??? note "三类网关配错,分别怎么认"

    | 现象 | 多半是 | 动哪 |
    |---|---|---|
    | 401 / 403 | 凭证是对的,但不是这个网关签发的;或者 `BASE_URL` 少了路径、多了尾斜杠 | [config.md](config.md#凭证变量) |
    | 报模型名不存在 | 网关只认自己那套模型名,映射没配 | [config.md](config.md#模型变量) |
    | 一开局就换代,报"启动地板" | 窗口配小了:阈值低于角色的启动地板(协调者实测约 34k) | `--window`,见 [handoff.md](../guide/handoff.md#阈值怎么算) |

**怎么办**:先 `-v` 打一次生效值再动配置。窗口这一项尤其值得对 —— 开发这台机器的网关配的是
`claude-opus-5[1m]`,早先按 20 万算的话每 15 万就换一代,而它其实能跑到 95 万,**差 5 倍**,
长程活会被切得稀碎。

---

## 跑起来了但行为不对 {#行为不对}

这一组的症状都不是报错,而是**命令跑完了、退出码是 0,做的事情却不对**。
前四条是已确认的代码缺陷,issue 已提,这里给的是绕过办法,不是修法。最后一条是设计如此。

### `flower setup` 跑起来的是一个 agent {#setup-跑成了-agent}

**症状**:执行 `flower setup`,以为它会问端点和 token,结果它开始问"要做什么",
接着走完整的 go 流程,把 `setup` 这个词当成了任务描述。跑完之后凭证一个字都没写上。

**原因**:`cli.py:758` 的 `_CMDS` 只列了 `"go"`、`"run"`、`"once"`,漏了 `"setup"`。
补默认子命令那一步于是把 argv `["setup"]` 改写成了 `["go", "setup"]` ——
`setup` 从子命令降格成了 `go` 的第一个位置参数,也就是诉求本身。
**没有任何 argv 能走到配置向导。** 已报 [#11](https://github.com/ChenyuHeee/flower/issues/11)。

**怎么办**:Ctrl-C 掐掉,然后直接写配置文件。`setup` 本来做的也只是往这个文件里写字:

```bash
mkdir -p ~/.config/flower
cat > ~/.config/flower/.env <<'EOF'
ANTHROPIC_AUTH_TOKEN=sk-...
EOF
```

完整的变量名与凭证查找顺序见 [config.md](config.md#凭证变量)。
写完在任意目录跑一次 `flower -v`,启动时打印的生效端点就是核对结果。

### 全角 `？` 触发不了旁路问答 {#全角问号}

**症状**:按 [旁路问答](cli.md#旁路问答) 的写法在输入提示符里打了一句 `？这个目录能删吗`,
它没有起旁路顾问,而是把这句话当成对当前提问的回答,或者原样收进了收件箱。

**原因**:`cli.py:733` 连着做了两次 `startswith("?")` 判断,**两次用的是同一个 ASCII 字符**。
按代码意图,第二次本该判全角 `？`。中文输入法默认打出来的就是全角 —— 这个功能的主要用户
恰好一个都用不上。已报 [#12](https://github.com/ChenyuHeee/flower/issues/12)。

!!! warning "这一条会污染需求"
    落空的 `？` 不会报错,也不会被丢弃。它按普通输入处理:
    确认阶段当成对当前那个提问的回答,其余时候进收件箱。
    **一句你只想私下问一嘴的话,会被写进确认书。** 发现打错了,当场改
    `.flower/notes/需求.md`,那份文件才是下游的准绳。

**怎么办**:切半角再打 `?`,或者先打半角 `?` 再切回中文写正文。

### `once` 的累计花费永远是 `$0.00`,耗时永远 `0:00` {#once-计数为零}

**症状**:`flower once` 从头跑到尾,底部状态行的累计花费一直显示 `累计 $0.00`,
计时一直是 `0:00`,而同一个模型同一份活在 `go` 上是有数的。

**原因**:`once` 的 `render()` **每收到一个事件就新建一个 `Render`**,
累加器跟着一起重建,于是每次都从零开始。累计量是被反复清零,不是没统计。
已报 [#14](https://github.com/ChenyuHeee/flower/issues/14)。

**怎么办**:数字要准就走 `go`,那条路不受影响。只想要 `once` 的单轮形态又想看账,
跑完去查 `runs/manifest.json` —— 每一步的花费都记在那儿,那份记录是对的。
详见 [config.md](config.md#run-dir)。

### 放进 `plugin/` 的 skill 一直没被加载 {#plugin-不加载}

**症状**:按 [deploy.md](deploy.md#写一个-skill完整例子) 写好了 skill,目录结构也对,
但 agent 表现得像根本不知道它的存在 —— **没有报错,没有一行日志**。

**原因**:`plugin/` 没有打进 wheel。装出来的包里 `PLUGIN_DIR` 指向
`<site-packages>/plugin`,那个目录不存在,加载前的存在性判断直接静默跳过。
**`install.sh` 的三条路径全都中招**,只有源码检出的仓库能加载。
已报 [#15](https://github.com/ChenyuHeee/flower/issues/15)。

**怎么办**:先自查路径到底解析到了哪里。

```bash
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

打出 `False` 就是这一条。想用 skill,当下只有一个办法:**从源码检出跑**。

```bash
git clone https://github.com/ChenyuHeee/flower
cd flower
python3 -m venv .venv && .venv/bin/pip install -e .
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

`-e` 装出来的包指回检出目录,`PLUGIN_DIR` 落在真实的 `plugin/` 上,再跑那条自查会打出 `True`。

### `-T` 在 `go` 上看不出效果 {#trim-与-go}

**症状**:给 `flower go` 加了 `-T`,对比加与不加,行为完全一样,像是开关坏了。

**原因**:**这一条是设计如此,不是缺陷。** `go` 路径本来就默认开裁剪,
`-T` 表达的意图已经被满足,所以再给一次不会有变化。这条路上真正的开关是反向的
`--no-trim` —— 要关掉裁剪才需要显式给。`-T` 只在 `run` 和 `once` 上是有意义的开关。

**怎么办**:在 `go` 上想确认裁剪确实开着,用 `-v` 看启动打印,不要靠 `-T` 的有无来判断;
想关掉,给 `--no-trim`。开关的完整语义见 [cli.md](cli.md#全局开关)。

## 它说做完了但没做完 {#没做完}

[目标看守](../guide/goal.md) 的存在就是为了挡住这一类 —— 干活的 agent 有系统性的乐观偏差,
它知道自己做了什么,不知道自己漏了什么。但看守本身也会误判,而且误判的方向是有规律的。
下面五条按"它放行了不该放行的"和"它一直不放行"分开。

### 它说"这里没法验证",然后就过了 {#无法达成不是未达成}

**症状**:判定结果写着"当前环境无法验证这一条,视为达成",流程接着往下走。

**原因**:判定者把「无法达成」和「未达成」混成了一个结论。这两个是**不同的结论**,
[三个结论不是两个](../guide/goal.md#三个结论不是两个) 讲的就是这件事:
「未达成」是打回去接着做,「无法达成」是**停下来问人**,选择接受、改目标,还是说它判错了。
只有"达成/未达成"两个结论时,一个其实做不到的目标会让主 agent 一轮一轮空转到额度见底。

**怎么办**:**"这里验不了"永远不能当成达成**。给判定者的 `instructions` 里点名说清
在你这个场景里什么算做不到,让它该给「无法达成」的时候给「无法达成」。
真不想被停下来问,给 `--timeout 0`:无法达成时直接停,理由留在磁盘上,而不是蒙混过关。

### 它读了源码就说做完了 {#判产出物}

**症状**:判定理由写的是"代码里已经实现了 X"、"函数签名符合要求",
可是编译产物、命令输出、跑起来的服务,一个都没被碰过。

**原因**:判定者被引到了源码上。[判的是产出物,不是源码](../guide/goal.md#判的是产出物不是源码) ——
源码看起来对不对,和交出来的东西能不能用,是两件事。前者是干活那个 agent 已经确信的东西,
再确信一遍不产生新信息。

**怎么办**:判定项要写成对**产出物**的断言。"实现了导出功能"不算,
"跑 `./app export out.csv`,`out.csv` 有 3 列表头"才算。写目标那一步就该这么写,
否则判定者只能照着含糊的条目自己补齐。

### 判定者跑不了命令,于是它读了 Makefile 就放行 {#判定者不能跑命令}

**症状**:目标是"构建出一个能在 Linux 上跑的二进制",判定通过了。
你自己 `file` 一下,产物是 Mach-O,根本不是 ELF。

**原因**:判定者默认是 `judge(can_run=False)`,它手上**只有 `Read` / `Glob` / `Grep`**。
这三个工具读得了文件,**跑不了 `file`,也跑不了 `./app --version`**。
于是它退而求其次去读 Makefile,看见 Darwin 那个分支写着交叉编译,就认为条件满足了。
它没有说谎,它只是**在能力范围内找到了最像证据的东西**。

??? note "什么时候必须打开 `can_run`"
    判断依据很简单:**目标里出现了"构建出来的东西"这类词,就要开。**

    - 产物类:二进制、镜像、打包文件、生成的数据 —— 开
    - 行为类:服务起得来、命令返回 0、输出匹配某个模式 —— 开
    - 纯文本类:文档写没写、某个字段有没有加进 schema —— 不用开

    命令行上是 `--judge-can-run`,自己接线时给判定者角色 `judge(can_run=True)`。
    代价是判定者会真的执行命令,一轮判定更慢也更贵;换来的是它验的是**现场**,
    不是现场的说明书。见 [判定者能不能跑命令](../guide/goal.md#判定者能不能跑命令)。

**怎么办**:目标关于产物就开 `--judge-can-run`。不开的时候,
把"读得到就能判"作为写判定项的硬约束 —— 写不成这样的条目,说明这一条本来就需要跑命令。

### 判定清单十几条,一直打不过 {#清单长度}

**症状**:每一轮都被打回,差在哪列了一长串,越修越多,活干不完。

**原因**:清单是按"我要多严谨"写的,不是按"这活有几种失败方式"写的。
[清单的长度由有多少种失败方式决定](../guide/goal.md#清单的长度由有多少种失败方式决定):
`git clone && make && ./app` 这种任务,**三到五条就够** —— 构建成功、跑得起来、能用。
[HT002](../cases/ht002.md#那条查-flower-的清单自己把自己判失败了) 里那次真实的翻车,
一个"把仓库装起来跑"的任务被写成 **15 条**:只有 5 条在验东西能不能用,
6 条在验过程守没守规矩,还有 4 条**原理上就验不了**。

**怎么办**:改 `.flower/notes/目标.md`,那份文件才是判定的依据。逐条问"这一条对应哪一种失败",
答不上来的删掉。设目标那一步对验不了的条目本来就会喊,别把喊出来的那几条硬留着。

### 边界被写成了判定项 {#边界不是判定项}

**症状**:清单里出现了"没有跑过 `brew install`"、"没有改动项目目录之外的文件"这类条目,
判定者为了自证清白去查 `~/.zshrc` 的 mtime,查 `.flower/` 目录有没有被动过。

**原因**:边界和判定项约束的是不同的东西,混在一起就是 HT002 那次的主要成因
([根因一](../cases/ht002.md#根因一边界被当成了判定项))。

| | 约束什么 | 怎么遵守 |
|---|---|---|
| **边界** | 你**怎么干活**("只在项目目录内装""业务代码别动") | 靠**不越界**,不靠事后自证 |
| **判定项** | **交出来的东西**("跑起来了没有""结果对不对") | 靠当场验证 |

边界正是确认阶段被鼓励写满的一段。把它们逐条搬进清单,等于每加一条边界就多一条检查,
而这类检查大多验不了 —— 验不了的条目会拖着整轮判定一起失败。

**怎么办**:边界留在确认书的「边界」那一段,靠不越界遵守,不进判定清单。
真需要给个交代,一句话带过,**不要拆成六条**。

---

## 上下文与花费 {#上下文与花费}

长程运行里上下文和钱是同一个问题:上下文涨到顶,要么换代要么这一步炸;而每一轮重复说的话,
后面每一轮都要跟着重新付一次钱。

### 跑到一半它自己开了个新会话,说"换代" {#换代打断}

**症状** 事件流里出现 `handoff`,`payload["phase"]` 先 `near` 后 `done`,中间多花一轮写交接书的时间,
之后活照常往下干。

**原因** 上下文逼近阈值了。flower **不 compact** —— 它把当前会话的状态写成一份五段交接书,
起一个新会话读着它接着做。压缩会把"走不通的路"这类最贵的信息一起抹掉,而交接书是显式的、
落在磁盘上的、随时能改的:接手的会话读的就是那个文件。

**怎么办** 这是正常路径,不用管。换代不算重试 —— `attempts` 不涨(它数的是失败),
烧掉的 session_id 记在 `StepResult.retired` 里,对外的 `session_id` 永远是还活着的那个接班人
(见 [../guide/handoff.md#换代不算重试账怎么记](../guide/handoff.md#换代不算重试账怎么记))。
真想退回 SDK 的 auto-compact,用 `--no-handoff`。

??? note "阈值怎么来的,以及为什么默认值取得这么积极"
    `at = window - headroom`。`window` **默认 100 万**,按模型名判:名字里带 `haiku` 的算 20 万,
    其余算 100 万。`headroom` 默认 50k —— auto-compact 在 −33k 触发,换代要赶在它前面,
    而"写交接"本身还要再跑一轮,50k 同时满足这两件事。

    判大了不是硬错:真实窗口更小的话阈值永远够不着,请求会被 API 以「prompt 太长」退回,
    flower 认得这个信号 (`handoff.is_overflow()`),当场用机械拼的降级件换代,这一步不失败
    (见 [../guide/handoff.md#is_overflow把硬错变成当场换代](../guide/handoff.md#is_overflow把硬错变成当场换代))。

    实测值得一提:开发这台机器的网关配的是 `claude-opus-5[1m]`。早先按 20 万算的话每 15 万就换一代,
    而它其实能跑到 95 万 —— **差 5 倍**,长程活会被切得稀碎。

### 一开局就换代,而且停不下来 {#一开局就换代}

**症状** 报错里提到"启动地板",或者同一步反复换代,直到撞上 `max_generations=8`。

**原因** `window` 配小了,阈值低于这个角色的启动地板 —— 协调者实测约 34k,
光系统提示加工作台索引就占掉了。新会话一开口就越线,于是写交接、换代、再越线,永远不停
(换代不吃重试额度,那是有意的)。

**怎么办** `--window` 调到模型真实窗口,`-v` 会打印生效的端点与模型映射。正常长跑用不到 8 代,
真撞上了几乎一定是这个原因,错误信息里也直接这么说
(见 [../guide/handoff.md#一道防跑飞的闸](../guide/handoff.md#一道防跑飞的闸))。
另一个相关症状是"交接总是降级":原因写在 `runs/manifest.json` 的 `errors` 里。

### 停在半路,说预算到顶了 {#预算到顶}

**症状** 步骤没干完就停,理由是花费超限。

**原因** `AgentSpec(max_budget_usd=...)` 是**硬上限**,不是软提醒;`Runtime.total_cost()` 是当次运行的合计。

**怎么办** 抬上限之前先确认它不是在空转。一轮一轮被打回而每轮都没进展,通常是判定者该给
「无法达成」却给了「未达成」—— 一个其实做不到的目标会一直烧到额度见底
(见 [../guide/goal.md#三个结论不是两个](../guide/goal.md#三个结论不是两个))。
确认在正常干活,再抬上限。

### 这一跑为什么这么贵 {#为什么这么贵}

**症状** 花费远超预期,但看输出看不出钱花在哪。

**原因** 账不在模型的上下文里。每一步的 `session_id`、花费、重试次数、失败原因只记在
`runs/manifest.json`,**跨进程追加**。重试历史和错误原文也只在这里 —— 模型看不到,这是有意的:
被拒调用堆进上下文,主 agent 会学会"Bash 反正会被拦",连 `git status` 都不试
(`Runtime(keep_denials=1)` 默认已清,别调大)。

**怎么办** 打开 `runs/manifest.json` 按步骤对花费(磁盘布局见 [config.md#磁盘布局](config.md#磁盘布局))。
几个实测参考值:

| | 花费 |
|---|---|
| 一个 subagent 的启动地板(不可摊薄) | ~4.3k tokens |
| 协调者的启动地板 | ~34k tokens |
| `tests/smoke.py` 单 agent 全链路 | ~$0.21 |
| `tests/flow_demo.py` workflow 三种接法 | ~$0.39 |
| `tests/delegation.py` 分工 + 量上下文分布 | ~$0.71 |
| `tests/isolation.py` 三个 issue 三个 worktree | ~$0.9 |

### 上下文涨得比活干得快 {#上下文涨得快}

**症状** 每轮任务书里都在重复同一段纪律("先读文件再改""业务代码别动""改完跑测试"),
而执行者本来就在照着做。

**原因** 协调者说的每一句都进它自己的 transcript,transcript 只增不减。复述一遍纪律,
这一轮要付钱,**后面每一轮还要跟着这段重新付一次**。对方已经知道的事,复述的收益是零,
成本是永久的。

**怎么办** 纪律进机制,不进每轮的话:能用 `allowed_tools`、确认书的「边界」段、工作台索引表达的,
就别写进任务书;任务书只写这一轮变了什么。分工本身是省得最多的一层
(见 [../guide/context.md#第一层分工省得最多](../guide/context.md#第一层分工省得最多))。
resume 时旧的大工具结果可以用 `-T` 换成文件指针。

## 中断与接续 {#中断与接续}

### 进程被 kill 了,机器重启了 {#进程被杀}

**症状** 跑到一半没了,重开终端不知道该怎么捡回来。

**原因** 没什么要捡的。血缘 (`runs/lineage.json`) 记的是步骤名 → session_id,每一步结束就落盘,
写的时候先写 `.tmp` 再原子替换 —— 半途被杀不会留下半份文件。

**怎么办** 回到**同一个目录**再跑一次 `flower`,每一步接着上次那个会话:不会再盘问一遍需求,
不会重设一遍目标,连协调者试过哪些死路都还记得。什么都不想说就直接回车
(见 [../guide/continuity.md#进程被杀和机器重启](../guide/continuity.md#进程被杀和机器重启))。
判定者是例外 —— 它不是 `Step`,是 gate 里直接派出去的,从来不走血缘那条路,
所以每一轮都是全新的一双眼睛。

### 每次都从头开始,根本没接上 {#接不上}

**症状** 同一个目录再跑,它又把需求盘问了一遍。

**原因** 三种"对不上",flower 一律**静默退回从头开始,不报错** —— 接续是锦上添花,
它失效不该拦住人干活:

- `runs/lineage.json` 不在,或者里面的 `workspace` 和你现在的路径不一致(目录被拷走过就会这样)
- session 已经不在 `runs/sessions.db` 里(删过库)
- 血缘文件坏了

**怎么办** 先看 `runs/lineage.json` 在不在、`workspace` 对不对
(三个文件的职责见 [../guide/continuity.md#落在磁盘上的三个文件](../guide/continuity.md#落在磁盘上的三个文件))。
换了目录之后不接续是**有意的**:`project_key` 由工作区路径推导,旧 session 在新位置查不到。

### 想重开,但不想丢历史 {#想重开}

**症状** 需求已经换了一个方向,不想让它接着上次那摊说。

**原因** 默认行为就是接着说。在用过的目录里 `flower "顺便支持代码块高亮"` 不是新任务,
是又说了一句话。

**怎么办** `--new`。它是**归档不是删除**,旧东西留在 `notes/archive/` 里。
唤醒时会先报一行当前上下文规模,嫌大也走这条路。

### 断网了,它不报错也不动 {#断网}

**症状** 界面上没有新事件,进程还活着,看起来像卡住。

**原因** 断网被当成"等一等",不是失败。flower 挂着等:先探 DNS,再探 TCP,通了才继续
(见 [../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文](../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文))。
HT001 里这条被真实故障验证过
(见 [../cases/ht001.md#六断网续跑第一次被真实故障验证](../cases/ht001.md#六断网续跑第一次被真实故障验证))。

**怎么办** 等它,`-v` 能看到探测在跑。等待期间攒下的那些错误**不会进接续之后的上下文** ——
它们只落在 `runs/manifest.json`,接手的会话看到的是干净的现场,不会被一串超时带偏。

### 连按两次 Ctrl-C,收尾没做全 {#双重-ctrl-c}

**症状** 用 `kill`(SIGTERM)关掉和连按两次 Ctrl-C,留下的现场不一样。

**原因** 已知缺口。双 Ctrl-C 抛的是 `KeyboardInterrupt`:`cli.py` 里 `_drive` 的 `finally`
会调 `rt.close()`,但**不会**调 `rt.rescue()` —— 只有 SIGHUP/SIGTERM 的处理器调 `rescue()`。

**怎么办** 血缘两条路径都保得住(每步结束就原子落盘),所以再跑一次照样接得上,
这个缺口不会让你丢掉进度。要走完整收尾,用 `kill <pid>` 而不是狂按 Ctrl-C。

## 并行与隔离 {#并行与隔离}

### `not in a git repository` {#不是-git-仓库}

**症状** 开了隔离就起不来,报 `not in a git repository`。

**原因** `worker(..., isolate=True)` 靠 git worktree 给每个 agent 一份私有副本,
workspace 不是 git 仓库就建不出来。

**怎么办** 这条**不会静默退化** —— 要么真的在仓库里跑,要么把 `isolate` 关掉。
隔离保证的是"几个 agent 同时改、互相看不见对方的工作树",它不替你保证合并没冲突。

### 被隔离的 agent 写不进工作台 {#隔离写不进工作台}

**症状** subagent 报"写入权限被拒",脚本和产出落不了盘;或者产出落进了某一个 worktree,
别的 agent 看不见。

**原因** worktree 是每个 agent 的**私有副本**,工作台是跨 agent 的**共享层**。
共享的东西放进私有围栏里,别人当然拿不到。

**怎么办** 开隔离时把工作台指到**仓库外**:

```python
wb = Workbench(Path.cwd(), home=Path.cwd().parent / ".flower-proj").ensure()
```

放在工作区外面时 `Runtime` 会自动 `add_dirs` 授权;`Runtime(workbench=True)` 已经处理了这件事,
自建 `Workbench` 的授权要自己给。

!!! warning "工作台有两个默认位置,而且不一样"
    `Workbench(workspace)` —— CLI 和 `starter_flow()` 走的就是这条 —— 把工作台放在 `<workspace>/.flower`;
    而 `Runtime(workbench=True)`(也就是 `-W`)放的是 `<run_dir>/workbench`,即 `runs/workbench`。
    所以跑一次 `flower` 你会得到 `.flower/`,在 Python 里调 `Runtime(workbench=True)` **不会**。

### 跑 flower 有 `.flower/`,自己写脚本却没有 {#两个工作台默认值}

**症状** 确认书明明写进了 `.flower/notes/需求.md`,协调者却像没读过;**不报错**。

**原因** 手上是两个工作台对象。确认书写进 A 目录,注入 system prompt 的索引扫的是 B 目录,
"开局就知道需求文件在哪"那条承诺**静默失效**。两种错法都不报错:自己拼一个 `brief_path`
相对进程 cwd,和 `-W` 造的 `<run_dir>/workbench` 是两个目录;想从 `Runtime` 反着拿也不行 ——
`cli.py` 先调 `main()` 造 `Workflow`,之后才建 `Runtime`,那时 `brief_path` 早定死了。

**怎么办** 自己建一个 `Workbench`,把**同一个对象**同时挂给 `Workflow` 和 `Runtime`,位置就钉住了:

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[...])
rt = Runtime(workspace=".", workbench=wb)
```

`tests/trial_offline.py` 钉住了这一条:第 5 项断言确认书出现在 `prompt_block()` 里。
另外索引只注入**主 agent** 的 system prompt,subagent 继承不到(实测 $0.2461,`tests/prelude_live.py`)——
路径要由协调者转述下去,不是每个 subagent 自动知道
(见 [../guide/workflow.md#工作台要挂在-workflow-上](../guide/workflow.md#工作台要挂在-workflow-上))。

<!-- TODO(核实): `install.sh` 三种装法的优先级(是 uv → pip 兜底,还是也走 pipx),
     以及它提示 PATH 那句话的原文。上文"走到 pip 兜底那条路时"的措辞依赖这一点。 -->
<!-- TODO(核实): `check_credentials()` 的准确函数名与所在文件行号,写作时只有行为描述。 -->
<!-- TODO(核实): 判定者角色工厂的关键字。本文按 `judge(can_run=True)` 与命令行 `--judge-can-run` 写,
     未核对 `with_goal()` / `goal_step()` 上是否另有同名参数可直接透传。 -->
<!-- TODO(核实): `rt.rescue()` 具体做什么收尾(除血缘外还写了什么),源码出处待补;本节只写了"血缘两条路径都保得住"这一条可确认的事实。 -->
<!-- TODO(核实): 未使用 glossary 的逐词锚点(#换代 #接续 #工作台),锚点索引里只到 `#四个机制` 就截断了。术语首现的 glossary 链接留给协调者统一补。 -->
<!-- TODO(核实): 断网探测的重试间隔/上限没有数据,正文只写了"先探 DNS 再探 TCP",未给数字。 -->
