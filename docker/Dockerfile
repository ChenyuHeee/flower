# 容器里的 flower。
#
# 这个镜像同时是**可移植性那条约束的检验**:镜像里没有 Claude Code CLI、没有 Node,
# 只有 Python 和 claude-agent-sdk —— 请求靠 wheel 里自带的原生二进制发出去。
# 能在这里跑起来,"脱离 CLI"就不是纸上的说法。
#
# 为什么不把宿主的 .venv 拷进来:宿主那个是 macOS arm64 的 Mach-O 二进制(191M),
# 在 Linux 里跑不了。SDK 按平台发 wheel,容器必须自己装,才能拿到
# manylinux_2_17_aarch64 那一份。
FROM python:3.13-slim

# git:--isolate 要给每个 subagent 分 worktree
# ca-certificates:走 HTTPS 网关
# libstdc++6:SDK 自带的那个二进制是 Bun 编译的单文件,Linux 上要它;slim 镜像不带
# deb.debian.org 在墙内实测只有 32 KB/s(USTC 435 KB/s)。给了 APT_MIRROR 就换掉。
# docker/build 会自动带上;网络正常时留空即可。
ARG APT_MIRROR=""
RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|deb.debian.org|$APT_MIRROR|g; s|security.debian.org|$APT_MIRROR|g" \
            /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list 2>/dev/null || true; \
    fi \
 && apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates libstdc++6 \
 && rm -rf /var/lib/apt/lists/*

# 框架源码装进镜像,**不做 bind mount** —— 容器里的 agent 因此碰不到宿主的框架源码。
# 这正是在容器里跑的意义:subagent 的 Bash 是不受限的(flower 的白名单只管主线程)。
WORKDIR /opt/flower
COPY pyproject.toml ./
COPY flower ./flower
COPY examples ./examples

# 网络到 pypi.org 慢的时候(实测 20–32 KB/s)把 index 指到国内镜像 ——
# 阿里云实测 7.4 MB/s。docker/build 脚本会自动带上。
ARG PIP_INDEX_URL=""
RUN pip install --no-cache-dir ${PIP_INDEX_URL:+--index-url "$PIP_INDEX_URL"} .

# 唯一挂进来的是你的项目目录。凭证走 --env-file,不进镜像层。
WORKDIR /work
ENTRYPOINT ["flower"]
# 空 CMD:不带参数跑 `flowerbox` 时进交互输入(问你要做什么),
# 而不是打印 --help。命令行里那对引号是纯负担,见 cli.ask_for_prompt。
CMD []
