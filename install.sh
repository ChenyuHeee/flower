#!/bin/sh
# flower 安装器 —— 一句话装好可移植长程 agent 框架。
#
#   curl -fsSL https://raw.githubusercontent.com/ChenyuHeee/flower/main/install.sh | sh
#
# 它做的事:找一个 Python 工具安装器(uv > pipx > pip),从 GitHub 装 flower,
# 然后告诉你下一步。**不碰你的凭证** —— 第一次跑 `flower` 会问你要,存到
# ~/.config/flower/.env(装一次处处生效)。
set -eu

REPO="git+https://github.com/ChenyuHeee/flower.git"

BOLD=''; DIM=''; GRN=''; YLW=''; RED=''; OFF=''
if [ -t 1 ]; then
    BOLD=$(printf '\033[1m'); DIM=$(printf '\033[2m'); GRN=$(printf '\033[32m')
    YLW=$(printf '\033[33m'); RED=$(printf '\033[31m'); OFF=$(printf '\033[0m')
fi
say()  { printf '%s\n' "$*"; }
step() { printf '%s==%s %s\n' "$BOLD" "$OFF" "$*"; }
die()  { printf '%s! %s%s\n' "$RED" "$*" "$OFF" >&2; exit 1; }

# --- Python 版本(flower 要 3.10+)---------------------------------------
PY=""
for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then
        if "$c" -c 'import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null; then
            PY="$c"; break
        fi
    fi
done
[ -n "$PY" ] || die "需要 Python 3.10+。先装一个(brew install python / apt install python3),再跑本脚本。"

# --- 选一个安装器:uv > pipx > 装 uv > pip --user ------------------------
INSTALL=""
if command -v uv >/dev/null 2>&1; then
    step "用 uv 安装 flower…"
    uv tool install --force "$REPO" && INSTALL="uv"
elif command -v pipx >/dev/null 2>&1; then
    step "用 pipx 安装 flower…"
    pipx install --force "$REPO" && INSTALL="pipx"
else
    step "没有 uv/pipx —— 先装 uv(快、干净,不污染系统 Python)…"
    if curl -LsSf https://astral.sh/uv/install.sh | sh; then
        # uv 装到 ~/.local/bin
        [ -d "$HOME/.local/bin" ] && PATH="$HOME/.local/bin:$PATH"
        export PATH
        if command -v uv >/dev/null 2>&1; then
            step "用 uv 安装 flower…"
            uv tool install --force "$REPO" && INSTALL="uv"
        fi
    fi
    if [ -z "$INSTALL" ]; then
        step "退回 pip --user 安装 flower…"
        "$PY" -m pip install --user --upgrade "$REPO" && INSTALL="pip"
    fi
fi
[ -n "$INSTALL" ] || die "安装失败。手动试:uv tool install $REPO"

# --- flower 在 PATH 上吗 -------------------------------------------------
say ""
if command -v flower >/dev/null 2>&1; then
    step "${GRN}装好了${OFF} $(command -v flower)"
else
    BINDIR="$HOME/.local/bin"
    step "${GRN}装好了${OFF}(经 $INSTALL)"
    say "${YLW}! 但 flower 不在 PATH 上。${OFF}"
    say "  把这一行加进你的 ~/.zshrc 或 ~/.bashrc:"
    say "    ${BOLD}export PATH=\"$BINDIR:\$PATH\"${OFF}"
    say "  然后重开终端,或 source 一下。"
fi

# --- 下一步 --------------------------------------------------------------
say ""
say "${BOLD}下一步:${OFF}"
say "  cd 到任意项目目录,然后:  ${BOLD}flower${OFF}"
say "  ${DIM}第一次会问你要 API key / 网关地址,配一次存到 ~/.config/flower/.env,处处生效。"
say "  本机已经装了 Claude Code 并配好的话,flower 会直接借它的 token,连问都不问。${OFF}"
say ""
say "  ${DIM}文档:https://chenyuheee.github.io/flower/${OFF}"
