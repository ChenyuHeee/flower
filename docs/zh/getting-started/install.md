# 安装

装 flower 只需要 Python ≥ 3.10。运行时依赖只有一个 `claude-agent-sdk` —— 发请求用的原生二进制
就在它的 wheel 里,所以**不用装 Node,也不用装 Claude Code CLI**。这一页从零走一遍:一句话安装、
从源码安装、第一次配凭证、以及一条能证明"确实装对了"的命令。跑通之后去
[快速上手](quickstart.md)。

## 装之前:确认 Python

```bash
python3 -c 'import sys; print(sys.version_info >= (3, 10), sys.version.split()[0])'
```

输出 `True 3.13.7` 这样就够了。打出 `False` 或者根本没有 `python3`,先装一个
(`brew install python` / `apt install python3`),否则安装脚本会直接退出。

| 需要 | 不需要 |
|---|---|
| Python ≥ 3.10 (`pyproject.toml:5`;`install.sh:22-31` 也自查一遍) | Node.js |
| 到 API 端点的网络 | Claude Code CLI |
| 一份 API key 或网关 token(装完再给) | 宿主机 `~/.claude/` 里的设置(凭证是唯一例外,见下) |

包名 `flower`,版本 `0.1.0`,唯一运行时依赖 `claude-agent-sdk>=0.2.152`
(`pyproject.toml:2-6`)。`mkdocs-material` 只在 CI 建文档站时用,跑 flower 不需要。

## 一句话安装

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

装完终端上应该是这样(颜色略):

```text
== 用 uv 安装 flower…

== 装好了 /Users/you/.local/bin/flower

下一步:
  cd 到任意项目目录,然后:  flower
  第一次会问你要 API key / 网关地址,配一次存到 ~/.config/flower/.env,处处生效。
  本机已经装了 Claude Code 并配好的话,flower 会直接借它的 token,连问都不问。

  文档:https://chenyuheee.github.io/flower/
```

关键是那一行 `== 装好了 <绝对路径>` —— 它是脚本自己跑了一次 `command -v flower` 的结果
(`install.sh:60-61`)。打印出路径,就说明 `flower` 已经在 PATH 上。

### 安装器实际做了什么

[`install.sh`](https://github.com/ChenyuHeee/flower/blob/main/install.sh) 只做三件事:选一个
Python 工具安装器、从 GitHub 装、告诉你下一步。**它一个字都不碰你的凭证**(`install.sh:7-8`)。
安装源固定是 `git+https://github.com/ChenyuHeee/flower.git`(`install.sh:11`)。

安装器按顺序试,第一条能成的就停(`install.sh:33-57`):

| 顺序 | 触发条件 | 实际命令 | 可执行文件落在哪 |
|---|---|---|---|
| 1 | `uv` 在 PATH 上 | `uv tool install --force <REPO>` | uv 的 tool bin 目录,通常 `~/.local/bin/flower` |
| 2 | 没有 `uv`,但有 `pipx` | `pipx install --force <REPO>` | `~/.local/bin/flower` |
| 3 | 两个都没有 | 先 `curl -LsSf https://astral.sh/uv/install.sh \| sh` 装 uv,装上了就回到第 1 条 | 同第 1 条 |
| 4 | 第 3 条里 uv 也没装成 | `python3 -m pip install --user --upgrade <REPO>` | 用户脚本目录 —— **macOS 上不是 `~/.local/bin`** |

四种情况装的都是同一个 console script:`flower = "flower.cli:main"`(`pyproject.toml:12`)。装完也可以用
`python -m flower.cli` 调,效果一样(`cli.py:1263-1264`)。

!!! warning "重跑安装脚本会强制覆盖,没有确认提示"
    三个安装命令分别带 `--force`、`--force`、`--upgrade`(`install.sh:37`、`:40`、`:54`)。
    重跑一次就是把已有安装直接盖掉 —— 想升级正是这么做,但别指望它会先问你一句。

### `flower` 命令怎么上 PATH

`command -v flower` 查不到时,脚本会提示把 `$HOME/.local/bin` 加进 `~/.zshrc` 或 `~/.bashrc`
(`install.sh:62-70`):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

`uv tool install` 和 `pipx install` 都往这里放,这句提示对它们是准的。**但第 4 条路
(`pip install --user`)不一定** —— 那句提示里的目录是写死的,而 pip 的用户脚本目录跟平台走。
在 macOS 上它是 `~/Library/Python/3.13/bin`。自己查一下:

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', 'posix_user'))"
```

输出比如 `/Users/you/Library/Python/3.13/bin` —— 把那个目录而不是 `~/.local/bin` 加进 PATH,
然后重开终端或者 `source` 一下。

## 从源码装

要读代码、要改框架、要跑 `tests/` 里那些离线验证,就从源码装:

```bash
git clone https://github.com/ChenyuHeee/flower.git
cd flower
python3 -m venv .venv
.venv/bin/pip install -e .
```

执行完 `.venv/bin/flower --help` 应该打出 usage 那几行。

venv 里那个可执行文件的 shebang 是**绝对路径**,所以不必 activate,软链过去就能在任何目录用:

```bash
mkdir -p ~/.local/bin
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

`~/.local/bin` 在 PATH 上的话,`cd` 到任何项目目录敲 `flower`,走的都是这个 venv 里的解释器
和这份源码。

源码安装还多一个凭证落点:**仓库根的 `.env`**(查找顺序里排第 5,见
[配置 · 凭证查找优先级](../reference/config.md#凭证查找优先级))。开发时:

```bash
cp .env.example .env        # 填 ANTHROPIC_AUTH_TOKEN
```

`.env` 已经被 `.gitignore` 忽略,不会进版本库。pip / pipx / uv 装出来的 flower **没有**这个位置
可用 —— 它在 site-packages 里,没有"仓库根" —— 所以那种装法要用下面的全局凭证文件。

## 第一次跑:配凭证

`go`、`run`、`once` 三条跑活入口开头都调 `ensure_credentials()`(`cli.py:1013`、`:981`、`:1046`),
两道关:

1. **有没有** —— 按优先级找一遍,找不到就当场问你。
2. **能不能用** —— 真打一次 API。`max_tokens=16` 的最小请求(`env.py:120-123`),几乎不花钱。
   过期的 token、写错的网关地址,光看环境变量查不出来,不探就要跑到几分钟后才炸。

没有凭证时,第一次跑 `flower` 会停在这个界面(`cli.py:1179-1209`):

```text
== 配置 flower ========================================
第一次用?给一次凭证就行。
凭证会存到 /Users/you/.config/flower/.env(只你可读)。装一次,处处生效。

1. 你的 API key 或网关 token (Anthropic 官方的 sk-ant-… 或第三方网关签发的)
   >

2. 网关地址 (直接回车 = Anthropic 官方;第三方网关填它的 BASE_URL)
   >

3. 模型名 (直接回车 = 默认;网关有自己的模型名就填,如 claude-opus-5[1m])
   >

+ 存好了:/Users/you/.config/flower/.env
```

第 1 问必填,留空就打红字 `没给 token,取消。` 然后退出。第 2、3 问直接回车即可。
用官方端点就把第 2 问留空;第三方网关填它的根地址,**别带 `/v1`** —— flower 的探针打的是
`<BASE_URL>/v1/messages`(`env.py:162`)。

答完写出来的键(`cli.py:1199-1207`):

| 你填的 | 写进 `.env` 的键 |
|---|---|
| token 以 `sk-ant-` 开头 | `ANTHROPIC_API_KEY` |
| 其它 token | `ANTHROPIC_AUTH_TOKEN` |
| 网关地址非空 | `ANTHROPIC_BASE_URL` |
| 模型名非空 | `ANTHROPIC_MODEL`、`ANTHROPIC_DEFAULT_OPUS_MODEL`、`ANTHROPIC_DEFAULT_SONNET_MODEL` **三个一起写** |

文件位置是 `${XDG_CONFIG_HOME:-~/.config}/flower/.env`(`env.py:39-42`),**整份覆盖写**,
写完 `chmod 0o600`(`cli.py:1157-1168`)。这就是"装一次处处生效"的那个文件 ——
换项目目录不用重配,每个变量的含义见[配置](../reference/config.md#环境变量)。

### 本机装过 Claude Code 的话,可能一个问题都不问

凭证查找有一条**最后的回退**:读 `~/.claude/settings.json`,再读 `~/.claude/settings.local.json`,
从它们的 `env` 块里取 9 个凭证键(`env.py:56-75`、`:109-111`)。本机已经配好 Claude Code 的人,
直接跑 `flower` 就能开工,配置界面根本不会出现 —— `install.sh:77` 宣传的就是这条。

!!! warning "产品内那句"flower 不读 ~/.claude/settings.json"是错的"
    完全找不到凭证时,flower 打印的错误里最后一行是
    `flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。`
    (`env.py:184-194`,那一句在 `:192`)。**以代码为准:它读。**
    `env.py:56-75` 明确去读那两个文件的 `env` 块,只是只取 9 个凭证键,不接管别的任何设置。
    读到那句话时不要据此认定本机的 Claude Code 配置被忽略了。完整链条见
    [配置 · 凭证查找优先级](../reference/config.md#凭证查找优先级)。

### 想重新配的时候

`flower setup` 这个子命令注册过(`cli.py:1147-1149`),但 `_CMDS` 漏了它(`cli.py:758`),
于是 `flower setup` 会被改写成 `flower go setup` —— 把 "setup" 当成一句诉求跑一遍完整流程。
**目前没有任何命令行写法能到达那个子命令**,尽管好几处错误文案还在让你去跑它。要改凭证:

```bash
$EDITOR ~/.config/flower/.env
```

或者把那个文件里的 token 删掉再跑一次 `flower` —— 缺凭证那道关会重新问(前提是别的位置也没有,
比如 `~/.claude/settings.json`)。凭证被拒(HTTP 401 / 403)时也会当场弹出同一个界面让你重配,
最多给一次机会(`cli.py:1229-1244`)。

## 验证装好了没有

两级,由便宜到贵。

**第一级 —— 命令在不在(不花钱)**:

```bash
flower --help
```

看到这几行就说明 console script 装上了、也在 PATH 上:

```text
usage: flower [-h] [-w WORKSPACE] [-r RUN_DIR] [-v] [-W] [-T]
              {go,run,once,setup} ...

可移植长程 agent 框架
```

**第二级 —— 凭证、端点、原生二进制都通(几分钱)**:最便宜的真跑是 `once` ——
单 agent、默认只给 `Read` / `Glob` / `Grep` 三个只读工具,不开[目标看守](../reference/glossary.md#目标看守),
不开[工作台](../reference/glossary.md#工作台):

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

`-v` 会在开跑**之前**先打印当前生效的配置,token 只留前 4 位(`cli.py:1257-1259`;`env.py:197-211`):

```text
ANTHROPIC_AUTH_TOKEN = sk-1***(共 108 位)
ANTHROPIC_BASE_URL = https://cloud.infini-ai.com/maas
ANTHROPIC_MODEL = claude-opus-5[1m]
```

这几行确认没连错网关。接着是凭证探针和真正的运行:

```text
- 验一下凭证…
  * Read /path/to/any/repo/README.md
  这个仓库是……
  + 完成 1 轮 · $0.1741 · 用时 0:00
```

**没有步骤头。** `once` 走 `_run_once` → `rt.run()`,不经 `_drive` / `Workflow.run`,
而 `Event("step", …)` 只在 `workflow/base.py:220` 发出 —— 所以 `== 步骤名 ===== 1/1`
这种分隔行在 `once` 下不会出现,只有 `go` / `run` 才有。

**`+ 完成` 那一行出现就算通过**,它同时证明了三件事:凭证能用、端点连得上、
`claude-agent-sdk` wheel 里的原生二进制在这台机器上跑得起来。看到
`- 验一下凭证…` 下面跟着 `! 凭证被拒` 或 `! 网关地址或模型名不对`,去下面的排错表。

!!! note "`once` 的用时和累计花费显示为 0"
    `once` 给每个事件新建一个渲染器(`cli.py:1060`、`:579-581`),所以 `用时` 恒为 `0:00`、
    状态行里的 `累计 $` 也从不累积 —— **单步那个花费是真的,时间不是**。

    上面那行的 `1 轮 · $0.1741` 是**有出处的实测**:2026-09-06 在 Linux/arm64 容器里,
    经 `cloud.infini-ai.com/maas` 发出的一次真实请求(`docker/README.md:24-25`),
    也就是 Opus 5 + 1M 窗口的**单轮地板价**。你自己跑上面那条命令要读一遍仓库,
    轮数更多,花费也会比这个地板价高一些。
    完整的账在 `runs/manifest.json` 里,见[配置 · 磁盘布局](../reference/config.md#磁盘布局)。

## 装不上的时候

| 症状 | 原因 | 怎么办 |
|---|---|---|
| `需要 Python 3.10+。先装一个…` | `python3` 和 `python` 都不满足 3.10+(`install.sh:31`) | `brew install python` / `apt install python3`,再跑一次脚本 |
| 脚本说装好了,但 `flower: command not found` | 装到了不在 PATH 上的目录 | 见上面"`flower` 命令怎么上 PATH"。走到 `pip --user` 那条路时,macOS 上是 `~/Library/Python/3.X/bin` |
| `安装失败。手动试:uv tool install git+https://…` | 所有路径都失败,通常是到 GitHub 或 PyPI 的网络不通 | 按提示手动跑一次,看真实报错 |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。`(4 行) | 非交互环境(管道、CI、`nohup`)下没凭证 —— 那里不会弹配置界面,直接退出 | 先在真终端里跑一次 `flower` 配好,或者直接写 `~/.config/flower/.env` |
| `! 凭证被拒:HTTP 401 …` | token 过期或写错 | 交互终端里会当场让你重配;非交互则退出 |
| `! 网关地址或模型名不对:HTTP 404 …` | `ANTHROPIC_BASE_URL` 或模型名不对 | BASE_URL 写到网关根,别带 `/v1`;模型名用网关自己的那套 |
| `(探针没打通:… —— 当作网络问题,照常开跑)` | DNS / TCP / 超时 / 5xx | **不是凭证问题**,flower 有意不让你重配,照常开跑,交给[韧性](../reference/glossary.md#韧性)那一层 |
| `! 标准输入不是终端,没人能回答提问` | 在管道或 CI 里跑 | 加 `--timeout 0` 让它自己判断,别等人 |
| `flower setup` 跑起来在问"要做什么" | `_CMDS` 漏了 `setup`(`cli.py:758`) | 直接改 `~/.config/flower/.env`,见上面"想重新配的时候" |

## 下一步

- [快速上手](quickstart.md) —— 进一个项目目录,跑通第一件真活。
- [配置](../reference/config.md) —— 全部环境变量、凭证优先级、`.env` 语法、磁盘上留下什么。
- [命令行](../reference/cli.md) —— 全部子命令和开关。
- [部署](../reference/deploy.md) —— 容器里跑、用 plugin 分发领域能力。
- [术语表](../reference/glossary.md) —— 文档里每个词的准确含义。
