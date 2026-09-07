# 部署与扩展

把 flower 搬到别处要处理三件事:容器(围住不受限的 Bash,顺便检验"脱离 CLI"这句话)、
[plugin](glossary.md#plugin)(领域能力随仓库走,不看宿主机装了什么)、文档站(推到 `main`
就自动发,`install.sh` 挂在 Pages 域名上)。三节互相独立,按需要读。

## 一、容器

### 为什么要容器

**一是围起来。** 干活的[执行者](glossary.md#执行者)有**不受限的 Bash** —— flower 的 Bash
白名单(`delegate_guard`)只管[主线程](glossary.md#主线程),派出去的人要能跑测试,所以是有意的。
容器里只挂你的项目目录,框架源码在镜像内的 `/opt/flower`,宿主别的地方看不见。

**二是它本身就是[可移植](glossary.md#可移植)那条约束的检验。** 镜像里没有 Claude Code CLI、
没有 Node,只有 Python 和 `claude-agent-sdk` —— 请求靠 wheel 自带的原生二进制发出去。
能在这里跑起来,"脱离 CLI"就不是纸上的说法。

实测通过(2026-09-06,macOS 15 / arm64 / colima + docker 28.4.0):

| 验的是什么 | 结果 |
|---|---|
| 镜像里有没有 CLI | `claude`、`node`、`npm`、`npx` **都不存在** |
| 自带二进制 | `\177ELF`(207M) |
| 真实请求 | 经 `cloud.infini-ai.com/maas` 发出并拿到回答,`$0.1741 / 1 轮`(Opus 5 + 1M 窗口的单轮地板就是这个价) |
| 文件归属 | 容器内写 `/work` 的文件在宿主是 `hechenyu:staff`,映射正确 |
| 宿主可见性 | 容器里 `ls /Users` → `No such file or directory` |

### 镜像里装了什么

基础镜像 `python:3.13-slim`,上面 apt 只装三个包。每一样都有理由:

| 装的 | 为什么 |
|---|---|
| `python:3.13-slim` | 只要 Python ≥ 3.10。不装 Node、不装 claude CLI |
| `git` | `--isolate` 要给每个 [subagent](glossary.md#subagent) 分 worktree |
| `ca-certificates` | 走 HTTPS 网关 |
| `libstdc++6` | SDK 自带的二进制是 Bun 编译的单文件,Linux 上要它;slim 镜像不带 |

框架源码进镜像的方式是 `COPY`,**不是 bind mount** —— 容器里的 agent 因此碰不到宿主的框架源码:

| 镜像内路径 | 内容 | 来自 |
|---|---|---|
| `/opt/flower` | `pyproject.toml`、`flower/`、`examples/`,并在此 `pip install .` | `COPY` |
| `/work` | 工作目录(`WORKDIR`),运行时挂宿主的 `$PWD` | `docker run -v` |

入口是 `ENTRYPOINT ["flower"]`,`CMD` 是空的 —— 不带参数跑容器时进交互输入
(它问你要做什么),而不是打印 `--help`。这样就不必在 shell 里给一句中文诉求打引号。

### 为什么不能把宿主的 `.venv` 挂进去

SDK 按平台发 wheel,自带的二进制是平台专属的:

```text
宿主   claude_agent_sdk-0.2.152-py3-none-macosx_11_0_arm64.whl
       → _bundled/claude 是 Mach-O 64-bit arm64,191M
容器   claude_agent_sdk-0.2.152-py3-none-manylinux_2_17_aarch64.whl
```

挂进去跑不了,所以镜像必须自己 `pip install`。反过来说这也是可移植性的证据:同一个
`pyproject.toml`,换平台就换一份原生二进制,框架代码一行不用改。

### 两个脚本

| 脚本 | 做什么 |
|---|---|
| [`docker/build`](https://github.com/ChenyuHeee/flower/blob/main/docker/build) | 构建镜像。`cd` 到仓库根,`docker build -f docker/Dockerfile -t flower-box .`;`FLOWER_MIRRORS=1`(默认)时先从 registry 镜像拉 `python:3.13-slim` 再 retag,并带上 pip / apt 的 `--build-arg` |
| [`docker/flowerbox`](https://github.com/ChenyuHeee/flower/blob/main/docker/flowerbox) | 跑一次。检查凭证文件 → 检查 `$PWD` 挂不挂得进去 → 判断有没有 TTY → `docker run` |

`docker/build` 的开关,全部走环境变量:

| 变量 | 默认 | 语义 |
|---|---|---|
| `FLOWER_IMAGE` | `flower-box` | 镜像 tag |
| `FLOWER_MIRRORS` | `1` | `0` = 一个镜像源都不换,全走上游 |
| `FLOWER_REGISTRY` | `dockerproxy.net` | 从这里拉基础镜像再 retag 成 `python:3.13-slim`,让 `FROM` 命中本地 |
| `FLOWER_PIP_INDEX` | `https://mirrors.aliyun.com/pypi/simple/` | 传给 `--build-arg PIP_INDEX_URL` |
| `FLOWER_APT_MIRROR` | `mirrors.ustc.edu.cn` | 传给 `--build-arg APT_MIRROR` |

后三个只在 `FLOWER_MIRRORS=1` 时起作用 —— `FLOWER_MIRRORS=0` 那条分支根本不设 build-arg。

`docker/flowerbox` 认两个:

| 变量 | 默认 | 语义 |
|---|---|---|
| `FLOWER_HOME` | 脚本自己位置往上一级(即仓库根) | 去哪找 `.env`。找不到 `$FLOWER_HOME/.env` 直接退出 1 |
| `FLOWER_IMAGE` | `flower-box` | 跑哪个镜像 |

`FLOWER_HOME` 从脚本自己的位置推出来,不写死路径,所以仓库克隆到哪都能用。

### 跑起来

```bash
docker/build                       # 一次就够
cd ~/任意项目目录                   # 必须在 $HOME 下面,见下面的挂载边界
/path/to/flower/docker/flowerbox   # 不带参数 → 它问你要做什么,不用打引号
```

网络到 pypi.org / Docker Hub 正常的话,构建这样跑:

```bash
FLOWER_MIRRORS=0 docker/build
```

`flowerbox` 的参数和 `flower` 完全一样 —— 它把 `"$@"` 原样接在 `ENTRYPOINT` 后面。
`--clarify-only`、`--asks N`、`--timeout 秒`、`--isolate`、`-v` 都照给,全表见[命令行](cli.md):

```bash
cd ~/proj
/path/to/flower/docker/flowerbox --clarify-only -v
/path/to/flower/docker/flowerbox "帮我做一个 X"
```

真正执行的是这一行(`-t` 只在有 TTY 时加,见下):

```bash
docker run -i $TTY --rm \
    --env-file "$FLOWER_HOME/.env" \
    -v "$PWD:/work" \
    -w /work \
    "$IMAGE" "$@"
```

### 挂载边界与持久化

```text
宿主 $PWD  ──挂载──>  /work       ← agent 在这里干活,产出留在宿主
镜像内                /opt/flower ← 框架源码,**没挂载**,改不到宿主
```

所以在 `flower/human-test/HT001` 这种仓库内的子目录里跑也是安全的:挂进去的只有 `HT001`,
框架源码不在挂载范围内。

| 东西 | 退出后还在吗 | 为什么 |
|---|---|---|
| 宿主 `$PWD` 下的一切,含 `runs/`、[工作台](glossary.md#工作台) `.flower/` | 在 | 它就是被挂成 `/work` 的那个目录 |
| 容器内其它路径写的东西 | 不在 | `--rm`,容器退出即删 |
| 凭证 | 不进镜像层 | 走 `--env-file`;`.dockerignore` 里排掉了 `.env`,就算 `COPY . .` 也带不进去 |

!!! danger "项目目录必须在 `$HOME` 下面,否则产出静默丢失"
    **colima 默认只把 `$HOME` 挂进 VM**(`mount | grep virtiofs` → `mount0 on /Users/<你>`)。
    在 `/tmp` 之类的地方跑,`-v` 会在 VM 里建一个**空目录**,写进去的东西宿主永远看不到,
    **而且不报错** —— 产出、[需求确认书](glossary.md#需求确认书)、`runs/` 全部丢掉。踩过一次:
    一次 `once` 跑完 $0.17 花掉了,`runs/` 在宿主上根本不存在。

    `flowerbox` 现在会挡住这种情况:`$PWD` 在 `$HOME` 下直接放行;不在的话,它往 `$PWD` 里写一个
    探针文件,再起一个容器 `test -f /work/<探针>` 实测(配了额外挂载也能过)。过不了就退出 1,
    并告诉你 `colima start --mount '<路径>:w'`。探针要起容器,所以得先 `docker/build`。

### 凭证

走 `docker run --env-file`,**不进镜像层**。`flowerbox` 读的是 `$FLOWER_HOME/.env`,
默认就是仓库根的 `.env`:

```bash
cp .env.example .env       # 填 token;.env 已被 gitignore
```

注意 `flower setup` 写的是 `~/.config/flower/.env`,**那个路径 `flowerbox` 不看**。
已经用 `setup` 配好、不想再拷一份的话,把 `FLOWER_HOME` 指过去:

```bash
FLOWER_HOME=~/.config/flower /path/to/flower/docker/flowerbox
```

键名、优先级、网关怎么填,见[配置](config.md)。

!!! warning "没有 TTY 时,提问会一直卡到 `--timeout`"
    `flowerbox` 只在 `[ -t 0 ]` 时加 `-t` —— `docker run -t` 在管道 / CI 里会直接报
    "the input device is not a TTY";`-i` 一直要,不然 stdin 根本进不去。

    回答提问走标准输入。没有 TTY 时 `input()` 第一次就抛 `EOFError` → 当前问题被当成
    "输入已关闭"跳过,而且**回答线程直接退出**,于是第二个问题起没人接,只能干等满
    `--timeout`(默认 1800 秒)。无人值守要显式 `--timeout 0`。脚本检测到没有 TTY 时会
    先打一行提醒。

### git submodule

`.gitmodules` 里只有一条:

| path | url | 是什么 |
|---|---|---|
| `human-test/HT001` | `https://github.com/ChenyuHeee/cppide.git` | [HT001](../cases/ht001.md) 那次运行**产出的**代码仓库,留档用 |

普通 `git clone` 不会拉它,`human-test/HT001` 就是个空目录(`git submodule status` 前面
带 `-` 就是这个状态)。要不要管它:

| 你想干什么 | 要初始化吗 |
|---|---|
| 跑 flower、建镜像 | **不要**。`.dockerignore` 排掉了 `human-test/`,而 `Dockerfile` 本来也只 `COPY` `pyproject.toml` / `flower` / `examples` |
| 在本地翻 HT001 的产出代码 | 要:`git submodule update --init human-test/HT001`,或者一开始就 `git clone --recurse-submodules` |

### 国内网络:为什么有那一堆镜像替换

这套东西在墙内装的时候,慢的不是带宽而是国际线路。默认的 `docker/build` 已经把该换的都换了,
`FLOWER_MIRRORS=0` 一键全关。下面是实测数据和四处替换的原委 —— 网络没这个问题就不用读。

??? note "实测速度表与四处替换(2026-09-06,macOS/arm64)"

    | 源 | 速度 |
    |---|---|
    | `pypi.org`(索引) | 32 KB/s |
    | `files.pythonhosted.org`(包文件) | **284 B/s** |
    | `github.com`(直连 release asset) | 22 KB/s |
    | `cloud-images.ubuntu.com` | 382 B/s |
    | `deb.debian.org` | 32 KB/s |
    | `ports.ubuntu.com`(VM 内) | 26 KB/s |
    | `download.docker.com` | **连不上**(HTTP 000);VM 内 4 KB/s |
    | `mirrors.tuna.tsinghua.edu.cn` | **连不上** |
    | `mirrors.aliyun.com/pypi`(**包文件**) | 1.4 MB/s(宿主)/ 152 KB/s(VM 内) |
    | `mirrors.ustc.edu.cn/ubuntu-cloud-images` | **28 MB/s** |
    | `mirrors.ustc.edu.cn/ubuntu-ports`(VM 内) | 1.95 MB/s |
    | `mirrors.ustc.edu.cn/debian` | 435 KB/s |
    | `ghfast.top`(GitHub 代理) | **2.5 MB/s** |
    | `gh-proxy.com`(GitHub 代理) | 1.5 MB/s |
    | `dockerproxy.net`(Docker Hub 代理) | 可用(直接返回 manifest) |

    量的时候别把**索引页**当成包文件:`mirrors.aliyun.com/pypi/simple/` 那个页面有 7.4 MB/s,
    而真正 95.9 MB 的 wheel 只有 1.4 MB/s(VM 内 152 KB/s —— colima 的用户态网络有损耗)。
    按包文件的数字估时间。

    **替换点 1 —— colima 的 VM 镜像。** colima 用的不是普通 Ubuntu cloud image,而是它自己
    **预装了 docker** 的定制镜像(`abiosoft/colima-core` 的 release asset),所以起 VM 时不需要
    apt 装 docker,也就绕开了连不上的 `download.docker.com`。自己下好再用 `--disk-image` 喂给它:

    ```bash
    A=https://github.com/abiosoft/colima-core/releases/download/v0.9.0-2/ubuntu-24.04-minimal-cloudimg-arm64-docker.qcow2
    mkdir -p ~/.colima/images
    curl -sSL -C - -o ~/.colima/images/colima-arm64-docker.qcow2 "https://ghfast.top/$A"
    # 校验:digest 从 GitHub API 拿。别跳过 —— 这是要当 VM 跑的东西
    curl -sSL https://api.github.com/repos/abiosoft/colima-core/releases/tags/v0.9.0-2 \
      | python3 -c "import json,sys;[print(a['digest'],a['name']) for a in json.load(sys.stdin)['assets'] if a['name'].endswith('arm64-docker.qcow2')]"
    shasum -a 256 ~/.colima/images/colima-arm64-docker.qcow2

    colima start --disk-image ~/.colima/images/colima-arm64-docker.qcow2 \
                 --cpu 4 --memory 6 --disk 20
    ```

    代理会中途断流(实测 curl 56),`-C -` 断点续传重跑几次就行。

    **替换点 2 —— VM 里的 apt。** 即便用了预装 docker 的镜像,lima 的 boot 脚本
    `30-install-packages.sh` 还是会为了装 `rsync` 跑一次 `apt-get update` ——
    打 `ports.ubuntu.com`(26 KB/s)和 `download.docker.com`(4 KB/s),会卡到几十分钟。

    处置(**先读 `/mnt/lima-cidata/boot.sh` 再动手**:它对失败的 boot 脚本只是 `WARNING` +
    `CODE=1` 然后继续,而且末尾**一定**会写 `/run/lima-boot-done`,所以让那一步失败是安全的):

    ```bash
    export LIMA_HOME=~/.colima/_lima
    limactl shell colima -- sudo sh -c '
      cat > /etc/apt/sources.list.d/ubuntu.sources <<EOF
    Types: deb
    URIs: https://mirrors.ustc.edu.cn/ubuntu-ports/
    Suites: noble noble-updates noble-backports noble-security
    Components: main restricted universe multiverse
    Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
    EOF
      sed -i "s|https://download.docker.com|https://mirrors.ustc.edu.cn/docker-ce|g" \
          /etc/apt/sources.list.d/docker.list
      pkill -f "apt-get update"          # boot.sh 会继续走完并写完成标记
    '
    # colima start 随即正常退出;之后补上 rsync(现在 1.95 MB/s)
    limactl shell colima -- sudo sh -c 'apt-get update -q && apt-get install -y -q rsync'
    ```

    顺手把 `127.0.0.1 lima-colima` 加进 VM 的 `/etc/hosts`,消掉 `sudo: unable to resolve host`
    那串告警。

    **替换点 3 —— 基础镜像。** `docker/build` 先从 `dockerproxy.net` 拉 `python:3.13-slim`
    再 retag,让 Dockerfile 的 `FROM` 命中本地。实测 `dockerproxy.net` 直接返回 manifest
    (HTTP 200);`docker.1ms.run` / `docker.m.daocloud.io` 回 401、`hub.rat.dev` 302、
    `docker.xuanyuan.me` 403。

    **替换点 4 —— 容器内的 apt 和 pip。** `--build-arg APT_MIRROR=mirrors.ustc.edu.cn`
    (`deb.debian.org` 32 KB/s → USTC 435 KB/s)、
    `--build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`。注意 `PIP_INDEX_URL`
    同时也是 pip 自己认的环境变量,所以 `ARG` 一声明,RUN 里的 pip 就会读到它 ——
    不显式写 `--index-url` 也生效。

    一次性准备总耗时(在上面那个网络条件下)约 25 分钟,大头是 364 MB 的 VM 镜像和 95.9 MB
    的 SDK wheel。之后 `flowerbox` 启动就是秒级。

## 二、plugin {#plugin}

### 它是什么

跟着仓库走的**领域能力包**。框架代码不含任何领域知识,领域知识全部放在仓库根的 `plugin/`
目录里,和代码一起被 clone、一起被 review、一起被打 tag。

SDK 侧的接线在
[`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)
的 `build_options()` 里,两行:

```python
PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "plugin"
...
if use_plugin and PLUGIN_DIR.is_dir():
    opts["plugins"] = [{"type": "local", "path": str(PLUGIN_DIR)}]
```

配合 `setting_sources=[]`(下面单独讲),这就是 flower 能同时做到"[可移植](glossary.md#可移植)"
和"懂你的领域"的原因:它不问宿主机装了什么,只认仓库里带来的这一个目录。

### 目录布局

| 路径 | 放什么 | 什么时候生效 | 谁决定 |
|---|---|---|---|
| `plugin/.claude-plugin/plugin.json` | 包的身份:`name`、`description`、`version`、`author` | 加载时读一次 | — |
| `plugin/skills/<name>/SKILL.md` | 领域知识,按需加载 | **概率性** —— 模型判断相关才用 | 模型 |
| `plugin/agents/<name>.md` | subagent,独立上下文窗口 | 模型委派,或[流程](glossary.md#流程)里显式指定 | 模型 / 你 |
| `plugin/hooks/hooks.json` | 拦截工具调用 | **确定性** —— 匹配即执行 | 代码 |
| `plugin/.mcp.json` | 外部工具接入 | 注册成工具,和内置工具一样 | 模型 |

**概率性和确定性的区别是选型的关键,不是措辞的区别:**

- skill 是**摆在那儿的知识**。模型看到它的 `description`,觉得跟当前任务相关才会去读。
  相关性判断由模型做,所以同一句话跑两次,可能一次用了、一次没用。
- hook 是**代码**。匹配到事件就跑,和模型想不想、知不知道无关。flower 自己的
  [落盘](glossary.md#落盘)、[隔离](glossary.md#隔离)都是 hook,正是因为它们不能"有时生效"。

所以判据只有一条:**这件事必须每次都发生吗?** 必须 —— 写 hook。只是"知道了有好处" ——
写 skill。把必须的事写成 skill,等于把纪律押在模型的一次判断上。

现在仓库里 `plugin/` 只有两样东西:`.claude-plugin/plugin.json` 和 `skills/example/SKILL.md`。
`agents/`、`hooks/`、`.mcp.json` **都还不存在** —— 要用就自己建,目录名照上表写死。

### 写一个 skill:完整例子

以"生成发版说明"为例,从零到确认生效。

**第一步:建目录。** 目录名就是 skill 名,和 frontmatter 里的 `name` 保持一致。

```bash
mkdir -p plugin/skills/release-notes
```

**第二步:写 `plugin/skills/release-notes/SKILL.md`。** 文件名必须是 `SKILL.md`,大写。
格式是 YAML frontmatter + Markdown 正文,frontmatter 两个字段:

| 字段 | 作用 |
|---|---|
| `name` | skill 的标识。和目录名一致 |
| `description` | **模型选不选它,只看这一行**。写清"什么时候该用它",不要写"这是什么" |

一份能直接用的最小文件:

````markdown
---
name: release-notes
description: 整理发版说明时使用。当用户说"写 release notes""这版改了什么""发版"时用它。
---

# 发版说明

## 怎么取素材

```bash
git describe --tags --abbrev=0        # 上一个 tag
git log --oneline <上一个 tag>..HEAD   # 这一版的提交
```

## 输出格式

按三段分,每段是无序列表,每条一行,写用户能感知的变化,不写内部重构:

- **新增** —— 这版能干什么以前干不了的事
- **修复** —— 修了什么,一句话说清症状
- **不兼容** —— 升级要动手改什么。没有就整段不写

## 边界

- 版本号不要自己编,从 `pyproject.toml` 的 `version` 读。
- 拿不准某条提交对用户有没有感知,列出来问,不要替用户决定。
````

正文写什么没有强制格式 —— 它就是被读进上下文的一段文本。参照
[`plugin/skills/example/SKILL.md`](https://github.com/ChenyuHeee/flower/blob/main/plugin/skills/example/SKILL.md)
的写法:说清**什么时候用**、**步骤**、**输出成什么样**、**边界在哪**,比堆背景知识有用。

**第三步:确认它被加载了。** 分两半查,先查确定的那一半 —— 目录到底在不在:

```bash
cd /path/to/flower
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

打出 `/path/to/flower/plugin True` 才说明 `build_options()` 那个 `if` 会进去。
打出 `False` 就是没加载,而且**运行时不会报错**,见下面的警告。

再查模型那一半。仓库自带的 `example` skill 就是为这件事准备的 —— 它被调用时会输出一行
`flower 插件链路正常`:

```bash
flower once "验证 flower 插件链路" -v
```

`-v` 显示思考与工具结果,能看到 skill 有没有被调起来。看到那行字就是通了。**没看到不等于没装上**
—— skill 是概率性的,模型也可能只是没觉得需要。这时先回去看上面那条 `PLUGIN_DIR` 的 `True`/`False`,
那个才是确定的信号。

要给某个[执行者](glossary.md#执行者)点名开哪几个 skill,用 `worker(..., skills=[...])`
([`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py));
名字用 `SKILL.md` 里的 `name`,SDK 也接受 `插件名:skill 名` 这种限定写法。

!!! warning "pip / uv 装出来的 flower 里没有 `plugin/`"
    `PLUGIN_DIR` 是从 `flower/core/agent.py` 往上三层再进 `plugin/`。从源码 checkout 跑时那是仓库根的
    `plugin/`;但 wheel 只打包 `flower` 一个目录(`pyproject.toml` 里
    `[tool.hatch.build.targets.wheel] packages = ["flower"]`),装进 site-packages 之后
    `site-packages/plugin` 不存在,`PLUGIN_DIR.is_dir()` 为假 —— **静默跳过,不报错、不告警**。

    容器同理:`docker/Dockerfile` 只 `COPY` 了 `pyproject.toml`、`flower/`、`examples/`,
    `plugin/` 没进镜像。

    所以现在要用领域能力包,就从源码 checkout 跑。

### `setting_sources=[]` 为什么逼着领域能力走 plugin

同一个函数里还有这一行:

```python
"setting_sources": [] if portable else ["project"],
```

SDK 的默认是 `None` = 三个来源全读:`~/.claude/settings.json`(用户)、
`.claude/settings.json`(项目)、`.claude/settings.local.json`(本地)。flower 默认传 `[]`,
把它们**全部关掉**。

| | 读不读 | 后果 |
|---|---|---|
| `~/.claude/`(宿主机) | 不读 | 换台机器行为一致,不会因为"我这台配过"而结果不同 |
| 项目 `.claude/` | 不读 | 放在 `.claude/skills/`、`.claude/agents/` 里的东西在 flower 下**一条都不生效** |
| `plugin/` | 读 | 路径写死在代码里,跟着仓库走 |
| 凭证 | 不继承 | `~/.claude/settings.json` 里的 `env` 块也不读,必须自带 `.env`,见[配置](config.md) |

`.claude/` 不生效**不是配置漏了,是这条约束的定义**:只要还从宿主机读一个字节,"换台机器行为一致"
就不成立。领域能力于是只有一条通道 —— 随仓库走的 `plugin/`。

两个开关(都在 `build_options()` 上,默认值就是可移植那套):

| 参数 | 默认 | 改了会怎样 |
|---|---|---|
| `portable` | `True` | 传 `False` → `setting_sources` 变成 `["project"]`,开始读项目 `.claude/`(SDK 侧:要读 `CLAUDE.md` 必须含 `"project"`)。可移植性随之失效 |
| `use_plugin` | `True` | 传 `False` → 完全不挂 `plugin/`,领域能力全靠 `AgentSpec.instructions` |

顺带:`instructions` 走的是[叠加](glossary.md#叠加)(`system_prompt` 的 `append`),
和 plugin 是两条不同的通道 —— 前者每轮都在上下文里,后者按需加载。短而必须的纪律写 `instructions`,
长而偶尔用得上的知识写 skill。

## 三、文档站

你正在读的这个站是 mkdocs-material 建的,源文件就在仓库的 `docs/` 下,推到 `main` 就自动发。

| 环节 | 是什么 |
|---|---|
| 配置 | `mkdocs.yml`,`docs_dir: docs` |
| 多语言 | `mkdocs-static-i18n`,`docs_structure: folder` —— `docs/zh/`、`docs/en/`……默认语言是 `zh` |
| 依赖 | `docs-requirements.txt`(钉了版本)。**不是** `pyproject.toml` 里那个 `docs` extra —— CI 装的是前者 |
| 构建 | `mkdocs build --strict`。坏内链、nav 指向不存在的页面,直接让构建失败,不会静默发一个 404 出去 |
| 重定向 | `hooks/redirects.py`,构建**之后**按最终 URL 写 meta-refresh 桩页,把旧的扁平地址(`/start/`、`/workflow/`、`/case-ht001/`……)接到新位置 |
| 部署 | `.github/workflows/docs.yml` → `actions/upload-pages-artifact@v3` + `actions/deploy-pages@v4`,发到 GitHub Pages |

本地改文档:

```bash
pip install -r docs-requirements.txt
mkdocs serve                  # 本地预览
mkdocs build --strict         # 提交前跑一遍,和 CI 同一条命令
```

CI 的触发条件是 push 到 `main` **且**改动命中这几个路径,另外可以在 Actions 页面手动
`workflow_dispatch`:

```text
docs/**  mkdocs.yml  hooks/**  docs-requirements.txt  install.sh  .github/workflows/docs.yml
```

### `install.sh` 为什么从 Pages 发

构建那步末尾有一行:

```yaml
- run: cp install.sh site/install.sh
```

安装脚本被塞进站点产物,于是它挂在文档站的域名上,一句话安装长这样:

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

理由很实际:**`raw.githubusercontent.com` 在国内不通,而 `*.github.io` 通**(实测)。
脚本本身放在仓库根,只是发布时多拷一份 —— 不需要维护两份内容,也不需要额外的 CDN。

`install.sh` 自己做的事:挑一个 Python 工具安装器(`uv` > `pipx` > 装 `uv` > `pip --user`),
从 GitHub 装 flower,然后提示下一步。它**不碰凭证** —— 第一次跑 `flower` 会问,存到
`~/.config/flower/.env`。

<!-- TODO(核实): docker/Dockerfile 不 COPY plugin/,所以容器里领域能力包一定不生效。这是有意的
     (容器只用来验"脱离 CLI"),还是漏了?如果是漏了,页面里"要用 plugin 就从源码 checkout 跑"
     这句要改成给出容器侧的做法。 -->
<!-- TODO(核实): build_options() 从不设置 SDK 的 session 级 `skills=` 选项。按 SDK 文档,
     `skills=None` 意味着"不做 SDK 自动配置,CLI 自己的默认仍然生效",所以主 agent 那边
     plugin 里的 skill 到底会不会出现在可选列表里,没有实测过。页面里"跑一句看 example skill
     有没有被调起来"的验证步骤依赖这一点。 -->
