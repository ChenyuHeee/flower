# 在容器里跑 flower

两个用处:

1. **围起来。** 干活的 subagent 有**不受限的 Bash** —— flower 的 Bash 白名单
   (`delegate_guard`)只管主线程,派出去的人要能跑测试,所以是有意的。
   容器里只挂了你的项目目录,框架源码在镜像内(`/opt/flower`),宿主别的地方看不见。
2. **它本身就是「可移植」那条约束的检验。** 镜像里没有 Claude Code CLI、没有 Node,
   只有 Python 和 `claude-agent-sdk` —— 请求靠 wheel 自带的原生二进制发出去。
   能在这里跑起来,"脱离 CLI"就不是纸上的说法。

```bash
docker/build                       # 一次
cd ~/任意项目目录                   # 必须在 $HOME 下面,见下面「挂载边界」
/path/to/flower/docker/flowerbox   # 不带参数 → 它问你要做什么,不用打引号
```

`flowerbox` 的参数和 `flower` 完全一样(`--clarify-only` / `--asks N` /
`--timeout 秒` / `--isolate` / `-v`)。

**已实测通过**(2026-09-06,macOS 15 / arm64 / colima + docker 28.4.0):

- 镜像里 `claude`、`node`、`npm`、`npx` **都不存在**;自带二进制是 `\177ELF`(207M)
- 经 `cloud.infini-ai.com/maas` 发出真实请求并拿到回答:`$0.1741 / 1 轮`
  (Opus 5 + 1M 窗口的单轮地板就是这个价)
- 容器内写 `/work` 的文件在宿主是 `hechenyu:staff`,归属映射正确
- 容器里 `ls /Users` → No such file or directory

---

## 为什么不能把宿主的 `.venv` 挂进去

SDK 按平台发 wheel,自带的二进制是平台专属的:

```
宿主   claude_agent_sdk-0.2.152-py3-none-macosx_11_0_arm64.whl
       → _bundled/claude 是 Mach-O 64-bit arm64,191M
容器   claude_agent_sdk-0.2.152-py3-none-manylinux_2_17_aarch64.whl
```

挂进去跑不了。所以镜像必须自己 `pip install`。反过来说,这也是可移植性的证据:
同一个 `pyproject.toml`,换平台就换一份原生二进制,框架代码一行不用改。

## 镜像里装了什么,为什么

| | 为什么 |
|---|---|
| `python:3.13-slim` | 只要 Python ≥ 3.10。不装 Node、不装 claude CLI |
| `git` | `--isolate` 要给每个 subagent 分 worktree |
| `ca-certificates` | 走 HTTPS 网关 |
| `libstdc++6` | SDK 自带的二进制是 Bun 编译的单文件,Linux 上要它;slim 镜像不带 |

## 凭证

走 `docker run --env-file`,**不进镜像层**。`flowerbox` 默认读
`$FLOWER_HOME/.env`,而 `FLOWER_HOME` 从脚本自己的位置推出来(仓库根),
所以克隆到哪都能用;要指到别处就 `FLOWER_HOME=... flowerbox …`。

`.dockerignore` 里排掉了 `.env`,所以就算 `COPY . .` 也带不进去。

## 挂载边界

```
宿主 $PWD  ──挂载──>  /work      ← agent 在这里干活,产出留在宿主
镜像内                /opt/flower ← 框架源码,**没挂载**,改不到宿主
```

所以在 `flower/human-test/HT001` 这种仓库内的子目录里跑也是安全的:挂进去的只有
`HT001`,框架源码不在挂载范围内(容器里 `ls /Users` 直接 No such file or directory)。

### 项目目录必须在 `$HOME` 下面

**colima 默认只把 `$HOME` 挂进 VM**(`mount | grep virtiofs` → `mount0 on /Users/<你>`)。
在 `/tmp` 之类的地方跑,`-v` 会在 VM 里建一个**空目录**,写进去的东西宿主永远看不到,
**而且不报错** —— 产出、确认书、`runs/` 全部静默丢失。踩过一次:一次 `once` 跑完
$0.17 花掉了,`runs/` 在宿主上根本不存在。

`flowerbox` 现在会挡住这种情况:`$PWD` 在 `$HOME` 下直接放行;不在的话用探针实测
(配了额外挂载也能过),过不了就退出 1 并告诉你 `colima start --mount '<路径>:w'`。

## TTY

`flowerbox` 只在 `[ -t 0 ]` 时加 `-t` —— `docker run -t` 在管道 / CI 里会直接报
"the input device is not a TTY";`-i` 一直要,不然 stdin 根本进不去。回答提问走标准输入,没有 TTY 时
`input()` 第一次就抛 `EOFError` → 当前问题被当成"输入已关闭"跳过,而且**回答线程
直接退出**,于是第二个问题起没人接,只能干等满 `--timeout`(默认 1800 秒)。
无人值守要显式 `--timeout 0`。

---

## 国内网络:为什么有那一堆镜像替换

这套东西在墙内装的时候,慢的不是带宽而是国际线路。2026-09-06 在一台 macOS/arm64 上实测:

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

> 量的时候注意别把**索引页**当成包文件:`mirrors.aliyun.com/pypi/simple/` 那个页面
> 有 7.4 MB/s,而真正 95.9 MB 的 wheel 只有 1.4 MB/s(VM 内 152 KB/s ——
> colima 的用户态网络有损耗)。按包文件的数字估时间。

所以**四处**替换:

1. **colima 的 VM 镜像**。colima 用的不是普通 Ubuntu cloud image,而是它自己
   **预装了 docker** 的定制镜像(`abiosoft/colima-core` 的 release asset)——
   所以起 VM 时不需要 apt 装 docker,也就绕开了连不上的 `download.docker.com`。
   自己下好再用 `--disk-image` 喂给它:

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

2. **VM 里的 apt**。即便用了预装 docker 的镜像,lima 的 boot 脚本
   `30-install-packages.sh` 还是会为了装 `rsync` 跑一次 `apt-get update` ——
   打 `ports.ubuntu.com`(26 KB/s)和 `download.docker.com`(4 KB/s),会卡到几十分钟。

   处置(**先读 `/mnt/lima-cidata/boot.sh` 再动手**:它对失败的 boot 脚本只是
   `WARNING` + `CODE=1` 然后继续,而且末尾**一定**会写 `/run/lima-boot-done`,
   所以让那一步失败是安全的):

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

   顺手把 `127.0.0.1 lima-colima` 加进 VM 的 `/etc/hosts`,消掉
   `sudo: unable to resolve host` 那串告警。

3. **基础镜像**。`docker/build` 先从 `dockerproxy.net` 拉 `python:3.13-slim`
   再 retag,让 Dockerfile 的 `FROM` 命中本地。

4. **容器内的 apt 和 pip**。`--build-arg APT_MIRROR=mirrors.ustc.edu.cn`
   (`deb.debian.org` 32 KB/s → USTC 435 KB/s)、
   `--build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`。
   注意 `PIP_INDEX_URL` 同时也是 pip 自己认的环境变量,所以 `ARG` 一声明,
   RUN 里的 pip 就会读到它 —— 不显式写 `--index-url` 也生效。

**网络没这个问题就全都不需要:**

```bash
FLOWER_MIRRORS=0 docker/build
```

覆盖单项:`FLOWER_REGISTRY=...`、`FLOWER_PIP_INDEX=...`、
`FLOWER_APT_MIRROR=...`、`FLOWER_IMAGE=...`。

一次性准备总耗时(在上面那个网络条件下)约 25 分钟,其中大头是 364 MB 的 VM 镜像
和 95.9 MB 的 SDK wheel。之后 `flowerbox` 启动就是秒级。
