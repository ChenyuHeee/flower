# Installation

Installing flower only takes Python ≥ 3.10. There's exactly one runtime dependency,
`claude-agent-sdk` — the native binary that issues the requests ships inside its wheel, so
**you don't need Node, and you don't need the Claude Code CLI**. This page walks the whole thing
from zero: one-line install, install from source, first-time credential setup, and one command that
proves it actually works. Once that's through, go to [Quickstart](quickstart.md).

## Before installing: check Python

```bash
python3 -c 'import sys; print(sys.version_info >= (3, 10), sys.version.split()[0])'
```

Output like `True 3.13.7` is good enough. If it prints `False`, or there's no `python3` at all,
install one first (`brew install python` / `apt install python3`) — otherwise the install script
exits immediately.

| Needed | Not needed |
|---|---|
| Python ≥ 3.10 (`pyproject.toml:5`; `install.sh:22-31` checks again) | Node.js |
| Network access to the API endpoint | Claude Code CLI |
| An API key or gateway token (provide it after installing) | Settings in the host's `~/.claude/` (credentials are the one exception, see below) |

Package name `flower`, version `0.1.0`, sole runtime dependency `claude-agent-sdk>=0.2.152`
(`pyproject.toml:2-6`). `mkdocs-material` is only used when CI builds the docs site; running flower
doesn't need it.

## One-line install

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

After it finishes the terminal should look like this (colors omitted):

```text
== 用 uv 安装 flower…

== 装好了 /Users/you/.local/bin/flower

下一步:
  cd 到任意项目目录,然后:  flower
  第一次会问你要 API key / 网关地址,配一次存到 ~/.config/flower/.env,处处生效。
  本机已经装了 Claude Code 并配好的话,flower 会直接借它的 token,连问都不问。

  文档:https://chenyuheee.github.io/flower/
```

The line that matters is `== 装好了 <absolute path>` — it's the script's own `command -v flower`
result (`install.sh:60-61`). If a path is printed, `flower` is on PATH.

### What the installer actually does

[`install.sh`](https://github.com/ChenyuHeee/flower/blob/main/install.sh) does exactly three things:
pick a Python tool installer, install from GitHub, tell you the next step. **It doesn't touch your
credentials at all** (`install.sh:7-8`). The install source is hardcoded to
`git+https://github.com/ChenyuHeee/flower.git` (`install.sh:11`).

The installer tries in order and stops at the first one that works (`install.sh:33-57`):

| Order | Trigger | Actual command | Where the executable lands |
|---|---|---|---|
| 1 | `uv` on PATH | `uv tool install --force <REPO>` | uv's tool bin directory, usually `~/.local/bin/flower` |
| 2 | No `uv`, but `pipx` present | `pipx install --force <REPO>` | `~/.local/bin/flower` |
| 3 | Neither | First `curl -LsSf https://astral.sh/uv/install.sh \| sh` to install uv; if that works, back to case 1 | Same as case 1 |
| 4 | uv also failed to install in case 3 | `python3 -m pip install --user --upgrade <REPO>` | The user scripts directory — **not `~/.local/bin` on macOS** |

All four cases install the same console script: `flower = "flower.cli:main"` (`pyproject.toml:12`).
After installing you can also invoke it as `python -m flower.cli`, with identical behavior
(`cli.py:1263-1264`).

!!! warning "Re-running the install script force-overwrites, with no confirmation prompt"
    The three install commands carry `--force`, `--force`, and `--upgrade` respectively
    (`install.sh:37`, `:40`, `:54`). Re-running simply clobbers the existing installation — that's
    exactly how you upgrade, but don't expect it to ask first.

### Getting the `flower` command onto PATH

When `command -v flower` finds nothing, the script suggests adding `$HOME/.local/bin` to `~/.zshrc`
or `~/.bashrc` (`install.sh:62-70`):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Both `uv tool install` and `pipx install` put it there, so that advice is correct for them. **But
path 4 (`pip install --user`) may differ** — the directory in that message is hardcoded, whereas
pip's user scripts directory is platform-dependent. On macOS it's `~/Library/Python/3.13/bin`. Check
yourself:

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', 'posix_user'))"
```

Output like `/Users/you/Library/Python/3.13/bin` — add that directory to PATH instead of
`~/.local/bin`, then reopen the terminal or `source` your shell rc.

## Install from source

If you want to read the code, modify the framework, or run the offline checks in `tests/`, install
from source:

```bash
git clone https://github.com/ChenyuHeee/flower.git
cd flower
python3 -m venv .venv
.venv/bin/pip install -e .
```

After that, `.venv/bin/flower --help` should print the usage lines.

The executable inside the venv has an **absolute path** shebang, so there's no need to activate —
symlink it and it works from any directory:

```bash
mkdir -p ~/.local/bin
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

With `~/.local/bin` on PATH, typing `flower` in any project directory runs this venv's interpreter
and this source tree.

A source install also adds one more credential location: **`.env` at the repo root** (5th in the
lookup order, see
[Configuration · Credential lookup priority](../reference/config.md#凭证查找优先级)). During
development:

```bash
cp .env.example .env        # 填 ANTHROPIC_AUTH_TOKEN
```

`.env` is already in `.gitignore`, so it won't be committed. A flower installed via pip / pipx / uv
**does not** have this location available — it lives in site-packages, there is no "repo root" — so
that kind of install must use the global credential file below.

## First run: configuring credentials

The three live-run entrypoints `go`, `run`, and `once` all call `ensure_credentials()` up front
(`cli.py:1013`, `:981`, `:1046`), which is two gates:

1. **Do they exist** — walk the priority list; if nothing is found, ask you right there.
2. **Do they work** — actually hit the API once. A minimal request with `max_tokens=16`
   (`env.py:120-123`), costing next to nothing. An expired token or a mistyped gateway address can't
   be detected by staring at environment variables, and without the probe you'd only blow up minutes
   into the run.

With no credentials, the first `flower` run stops at this screen (`cli.py:1179-1209`):

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

Question 1 is required; leaving it blank prints the red `没给 token,取消。` and exits. For questions
2 and 3 you can just press Enter. Leave question 2 blank for the official endpoint; for a
third-party gateway enter its root address, **without `/v1`** — flower's probe hits
`<BASE_URL>/v1/messages` (`env.py:162`).

The keys written out from your answers (`cli.py:1199-1207`):

| What you entered | Key written into `.env` |
|---|---|
| Token starts with `sk-ant-` | `ANTHROPIC_API_KEY` |
| Any other token | `ANTHROPIC_AUTH_TOKEN` |
| Gateway address non-empty | `ANTHROPIC_BASE_URL` |
| Model name non-empty | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` — **all three at once** |

The file lives at `${XDG_CONFIG_HOME:-~/.config}/flower/.env` (`env.py:39-42`), is written as a
**full overwrite**, and gets `chmod 0o600` afterwards (`cli.py:1157-1168`). This is the "configure
once, works everywhere" file — switching project directories requires no reconfiguration. For the
meaning of each variable, see [Configuration](../reference/config.md#环境变量).

### If Claude Code is already installed on this machine, you may not be asked anything

Credential lookup has a **final fallback**: read `~/.claude/settings.json`, then
`~/.claude/settings.local.json`, and pull 9 credential keys out of their `env` blocks
(`env.py:56-75`, `:109-111`). Anyone who already has Claude Code configured can just run `flower` and
start working; the configuration screen never appears — that's what `install.sh:77` advertises.

!!! warning "The in-product line \"flower doesn't read ~/.claude/settings.json\" is wrong"
    When no credentials can be found anywhere, the last line of flower's error message is
    `flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。`
    (`env.py:184-194`; that sentence is at `:192`). **The code is authoritative: it does read it.**
    `env.py:56-75` explicitly reads the `env` blocks of those two files — it just takes only the 9
    credential keys and takes over no other setting. When you hit that line, don't conclude that this
    machine's Claude Code configuration is being ignored. For the full chain, see
    [Configuration · Credential lookup priority](../reference/config.md#凭证查找优先级).

### When you want to reconfigure

The `flower setup` subcommand is registered (`cli.py:1147-1149`), but `_CMDS` misses it
(`cli.py:758`), so `flower setup` gets rewritten into `flower go setup` — treating "setup" as a
request and running the full workflow on it. **There is currently no command-line spelling that
reaches that subcommand**, even though several error messages still tell you to run it. To change
credentials:

```bash
$EDITOR ~/.config/flower/.env
```

Or delete the token from that file and run `flower` again — the missing-credentials gate will ask
again (provided no other location has them either, e.g. `~/.claude/settings.json`). When credentials
are rejected (HTTP 401 / 403) the same screen pops up on the spot so you can reconfigure, with at
most one retry (`cli.py:1229-1244`).

## Verifying the install

Two levels, cheap to expensive.

**Level one — is the command there (free)**:

```bash
flower --help
```

Seeing these lines means the console script is installed and on PATH:

```text
usage: flower [-h] [-w WORKSPACE] [-r RUN_DIR] [-v] [-W] [-T]
              {go,run,once,setup} ...

可移植长程 agent 框架
```

**Level two — credentials, endpoint, and native binary all work (a few cents)**: the cheapest real
run is `once` — single agent, only the three read-only tools `Read` / `Glob` / `Grep` by default, no
[goal guard](../reference/glossary.md#目标看守), no
[workbench](../reference/glossary.md#工作台):

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

`-v` prints the currently effective configuration **before** the run starts, keeping only the first 4
characters of the token (`cli.py:1257-1259`; `env.py:197-211`):

```text
ANTHROPIC_AUTH_TOKEN = sk-1***(共 108 位)
ANTHROPIC_BASE_URL = https://cloud.infini-ai.com/maas
ANTHROPIC_MODEL = claude-opus-5[1m]
```

Those lines confirm you're not pointed at the wrong gateway. Then comes the credential probe and the
actual run:

```text
- 验一下凭证…
  * Read /path/to/any/repo/README.md
  这个仓库是……
  + 完成 1 轮 · $0.1741 · 用时 0:00
```

**No step headers.** `once` goes through `_run_once` → `rt.run()`, bypassing `_drive` /
`Workflow.run`, and `Event("step", …)` is only emitted at `workflow/base.py:220` — so separator lines
like `== 步骤名 ===== 1/1` never appear under `once`; only `go` / `run` have them.

**The run passes the moment the `+ 完成` line appears**, and that line simultaneously proves three
things: the credentials work, the endpoint is reachable, and the native binary inside the
`claude-agent-sdk` wheel runs on this machine. If `- 验一下凭证…` is followed by `! 凭证被拒` or
`! 网关地址或模型名不对`, go to the troubleshooting table below.

!!! note "`once` shows 0 for elapsed time and cumulative cost"
    `once` creates a fresh renderer for every event (`cli.py:1060`, `:579-581`), so `用时` is always
    `0:00` and the `累计 $` in the status line never accumulates — **the per-step cost is real, the
    time is not**.

    The `1 轮 · $0.1741` above is a **sourced, measured figure**: on 2026-09-06, in a Linux/arm64
    container, one real request issued through `cloud.infini-ai.com/maas` (`docker/README.md:24-25`)
    — i.e. the **single-round floor price** for Opus 5 + the 1M window. Running the command above
    yourself involves reading a repo, so you'll take more rounds and pay somewhat more than that
    floor. The full accounting is in `runs/manifest.json`, see
    [Configuration · Disk layout](../reference/config.md#磁盘布局).

## When it won't install

| Symptom | Cause | What to do |
|---|---|---|
| `需要 Python 3.10+。先装一个…` | Neither `python3` nor `python` satisfies 3.10+ (`install.sh:31`) | `brew install python` / `apt install python3`, then rerun the script |
| Script says it installed, but `flower: command not found` | Installed into a directory not on PATH | See "Getting the `flower` command onto PATH" above. On the `pip --user` path, macOS uses `~/Library/Python/3.X/bin` |
| `安装失败。手动试:uv tool install git+https://…` | Every path failed, usually no network to GitHub or PyPI | Run the suggested command manually to see the real error |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。` (4 lines) | No credentials in a non-interactive environment (pipe, CI, `nohup`) — the configuration screen won't appear there, it just exits | Run `flower` once in a real terminal and configure, or write `~/.config/flower/.env` directly |
| `! 凭证被拒:HTTP 401 …` | Token expired or wrong | In an interactive terminal it lets you reconfigure on the spot; non-interactive exits |
| `! 网关地址或模型名不对:HTTP 404 …` | `ANTHROPIC_BASE_URL` or the model name is wrong | Point BASE_URL at the gateway root, without `/v1`; use the gateway's own model names |
| `(探针没打通:… —— 当作网络问题,照常开跑)` | DNS / TCP / timeout / 5xx | **Not a credential problem** — flower deliberately doesn't make you reconfigure, it starts the run anyway and hands it to the [resilience](../reference/glossary.md#韧性) layer |
| `! 标准输入不是终端,没人能回答提问` | Running in a pipe or CI | Add `--timeout 0` so it decides for itself instead of waiting on a human |
| `flower setup` starts up asking "what should I do" | `_CMDS` misses `setup` (`cli.py:758`) | Edit `~/.config/flower/.env` directly, see "When you want to reconfigure" above |

## Next steps

- [Quickstart](quickstart.md) — enter a project directory and get the first real job done.
- [Configuration](../reference/config.md) — every environment variable, credential priority, `.env` syntax, what gets left on disk.
- [CLI](../reference/cli.md) — every subcommand and flag.
- [Deployment](../reference/deploy.md) — running in a container, distributing domain capabilities as a plugin.
- [Glossary](../reference/glossary.md) — the precise meaning of every term in the docs.
